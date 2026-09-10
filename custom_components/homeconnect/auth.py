# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Signing in to a Home Connect account.

The app opens the account's sign in page in a browser and waits to be sent
back to an address of its own with a one time code on it. Home Assistant
cannot be sent back to, so the user finishes in their own browser and hands
the address over, which is the same exchange with one manual step in it.

The code is worth nothing on its own. It is bound to a secret this generated
before opening the page and never sent anywhere until the exchange, so a code
read out of somebody else's address bar buys them nothing.
"""

from __future__ import annotations

import binascii
import hashlib
import json
import logging
import secrets
import time
from base64 import b64decode, urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from . import http
from .const import (
    API_HOST,
    AUTHORIZE_PATH,
    CLIENT_ID,
    REDIRECT_URI,
    SCOPES,
    TOKEN_EXPIRY_MARGIN,
    TOKEN_PATH,
)
from .errors import (
    HomeConnectAuthError,
    HomeConnectConnectionError,
    HomeConnectTooManyRequests,
)

_LOGGER = logging.getLogger(__name__)

# What the token endpoint calls a refusal that is about the credentials rather
# than about the request. A code that has been used already, a code that has
# expired and a refresh token the account has revoked all arrive as a 400
# saying this, rather than as the 401 the same rejection gets everywhere else.
INVALID_GRANT = "invalid_grant"


@dataclass(frozen=True)
class Tokens:
    """An access token with the refresh token that renews it."""

    access_token: str
    refresh_token: str
    expires_at: float
    # Who the account belongs to, where the cloud said. It is what one entry
    # is told from another, and it is not always given.
    account: str | None = None

    @property
    def expired(self) -> bool:
        """Due for renewal, counting the margin."""
        return time.time() >= self.expires_at - TOKEN_EXPIRY_MARGIN

    @property
    def usable(self) -> bool:
        """Still accepted by the service, margin or no margin."""
        return time.time() < self.expires_at


def verifier() -> str:
    """A fresh secret to bind an authorization to this sign in.

    Sixty-four bytes, which is what fills the length the specification allows
    for one of these once it is written down without padding.
    """
    return secrets.token_urlsafe(64)


def _challenge(code_verifier: str) -> str:
    """What the secret is published as: its digest, and nothing reversible."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(code_verifier: str, state: str) -> str:
    """Where to send the user to sign in.

    Asking for the login prompt is what the app does, and it is what stops a
    browser already signed in to the account from handing back a code without
    ever showing the user whose account it is.
    """
    query = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "prompt": "login",
        "state": state,
        "nonce": secrets.token_urlsafe(16),
        "code_challenge": _challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{API_HOST}{AUTHORIZE_PATH}?{urlencode(query)}"


# What the page the browser ends on knows how to be handed. Its own script
# looks for a single argument that decodes to one of these, rather than for
# named parameters, so an address copied off it can carry the answer that way
# instead of in plain sight.
HANDED_OVER = ("homeconnect://", "hcalexa://")


def _handed_over(query: str) -> str | None:
    """The address hidden in a base64 argument, if one is hidden there.

    Read out of the query as it was written rather than out of a parsed copy
    of it: base64 uses the plus sign, and a parsed query turns that into a
    space, which is the one edit that would stop it decoding.
    """
    for argument in query.split("&"):
        # Either alphabet, since the two differ only in the two characters
        # that a URL would otherwise have to escape.
        plainly = argument.replace("-", "+").replace("_", "/")
        padded = plainly + "=" * (-len(plainly) % 4)
        try:
            plain = b64decode(padded, validate=True).decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            continue
        if plain.startswith(HANDED_OVER):
            return plain
    return None


def code_from(answer: str) -> str:
    """The one time code out of whatever the user pasted back.

    Three things can be pasted and all three are taken. The address can carry
    the code as a plain parameter. It can carry the whole hand-off encoded
    into one argument, which is how the page meant for a phone is given its
    instructions. And somebody who has picked the code out themselves is not
    made to put it back into an address: a bare code has no query and no
    scheme, and nothing else looks like one.
    """
    pasted = answer.strip()
    if not pasted:
        raise HomeConnectAuthError("nothing was pasted back")
    written = urlparse(pasted).query
    query = parse_qs(written)
    found = query.get("code")
    if found:
        return found[0]
    handed = _handed_over(written)
    if handed is not None:
        inside = parse_qs(urlparse(handed).query).get("code")
        if inside:
            return inside[0]
    if "error" in query:
        raise HomeConnectAuthError(
            f"signing in was refused: {query['error'][0]}",
        )
    if "?" in pasted or "/" in pasted:
        raise HomeConnectAuthError("that address carries no code")
    return pasted


def _lifetime(payload: dict[str, Any]) -> float:
    """How long a token is good for, in seconds.

    A lifetime that is missing, or that arrives as something no number can be
    read out of, is treated as none at all: the pair is then due for renewal
    the moment it is used rather than being sent anywhere on a guess.
    """
    given = payload.get("expires_in")
    if given is None:
        return 0.0
    try:
        return float(given)
    except (TypeError, ValueError):
        _LOGGER.debug("could not read how long the token lasts from %r", given)
        return 0.0


def _account(payload: dict[str, Any]) -> str | None:
    """Who the tokens were issued to, out of the identity token beside them.

    The claims of one of these are the middle of three parts, written in the
    URL-safe alphabet without the padding. Nothing is verified here: the token
    came back over TLS from the endpoint we asked, and all that is wanted from
    it is a name to tell one account from another.
    """
    given = payload.get("id_token")
    if not isinstance(given, str) or given.count(".") != 2:
        return None
    claims_part = given.split(".")[1]
    padded = claims_part + "=" * (-len(claims_part) % 4)
    try:
        claims = json.loads(urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        _LOGGER.debug("the identity token did not read")
        return None
    subject = claims.get("sub") if isinstance(claims, dict) else None
    return str(subject) if subject else None


def _tokens_from(payload: Any) -> Tokens:
    if not isinstance(payload, dict):
        raise HomeConnectAuthError("the token endpoint returned no token pair")
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise HomeConnectAuthError("the token endpoint returned no token pair")
    return Tokens(
        access_token=str(access_token),
        refresh_token=str(refresh_token),
        expires_at=time.time() + _lifetime(payload),
        account=_account(payload),
    )


def _retry_after(headers: dict[str, str]) -> float | None:
    """How long the service asked us to wait, when it said."""
    given = headers.get("retry-after")
    if given is None:
        return None
    try:
        return float(given)
    except ValueError:
        # The header also allows a date, which the cloud does not use. Falling
        # back to the caller's own idea of a wait is better than failing over
        # a header nobody is going to send.
        return None


async def _token_request(
    session: aiohttp.ClientSession, form: dict[str, str], doing: str
) -> Tokens:
    """Ask the token endpoint for a pair, and say plainly when it says no."""
    status, payload, headers = await http.request(
        session,
        "POST",
        f"{API_HOST}{TOKEN_PATH}",
        headers={"Accept": "application/json"},
        data=form,
    )
    if status == 429:
        raise HomeConnectTooManyRequests(
            f"{doing} was asked to slow down", _retry_after(headers)
        )
    if status >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        described = (
            payload.get("error_description") if isinstance(payload, dict) else None
        )
        if status in (400, 401) or error == INVALID_GRANT:
            raise HomeConnectAuthError(
                f"{doing} was refused: {described or error or status}"
            )
        raise HomeConnectConnectionError(f"{doing} failed with status {status}")
    return _tokens_from(payload)


async def exchange(
    session: aiohttp.ClientSession, code: str, code_verifier: str
) -> Tokens:
    """Trade the one time code for a token pair.

    The address the sign in came back to is part of what is being proved, so
    the same one goes out here as went out with the request for the code.
    """
    return await _token_request(
        session,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": code_verifier,
        },
        "the sign in",
    )


async def renew(session: aiohttp.ClientSession, tokens: Tokens) -> Tokens:
    """Renew a pair that has expired, or is about to.

    The cloud hands back a new refresh token every time, and a caller that
    does not store it locks the account out, so the whole pair is returned
    rather than only the part that changed.
    """
    renewed = await _token_request(
        session,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": tokens.refresh_token,
        },
        "renewing the token",
    )
    # A renewal does not always carry an identity token, and the account has
    # not changed for want of being mentioned again.
    if renewed.account is None and tokens.account is not None:
        return replace(renewed, account=tokens.account)
    return renewed
