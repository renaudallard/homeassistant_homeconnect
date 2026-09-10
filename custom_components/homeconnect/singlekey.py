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

"""Signing in to SingleKey ID without a browser.

Home Connect accounts live at SingleKey ID, and the app reaches them the way
every phone app does: it opens a browser, the user signs in there, and the
browser is sent back to an address only the app can receive. Neither half of
that works from Home Assistant. The address the app is sent back to is a
private scheme no browser will open, and the one address a browser can reach
is a page built to hand the session on to a phone.

So this walks the same path the browser would, following the redirects itself
and stopping at the moment the account is handed back rather than trying to
open it. Nothing is scraped beyond what a form says it wants: the field names
below are the ones the login page puts in its own HTML.

It is the fragile way in and it is not pretending otherwise. A sign in that
wants a second factor, or a passkey, cannot be walked like this and says so
rather than failing obscurely, and the flow offers the other way in for those.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import aiohttp

from . import auth
from .const import REDIRECT_URI_APP
from .errors import HomeConnectAuthError, HomeConnectConnectionError

_LOGGER = logging.getLogger(__name__)

# What the login page calls its fields. The first is the one the page itself
# names in the HTML; the rest are what the page it leads to asks for.
EMAIL_FIELD = "UserIdentifierInput.EmailInput.StringValue"
PASSWORD_FIELD = "Password"
REMEMBER_FIELD = "RememberMe"
TOKEN_FIELD = "__RequestVerificationToken"

# The page carries a token per form, and posts back to itself using the one in
# the form the fields are in. The others belong to the passkey button and to
# the language switcher, and sending one of those is sending the wrong one.
FORM = re.compile(r'<form[^>]*class="form"[^>]*>(.*?)</form>', re.S)
TOKEN = re.compile(rf'name="{TOKEN_FIELD}"[^>]*value="([^"]+)"')
ASKS_FOR_PASSWORD = re.compile(r'type="password"', re.I)

# A sign in this cannot walk. Both are the account being better protected than
# a scripted login can cope with, which is worth saying plainly.
WANTS_MORE = re.compile(r"two-?factor|/2fa|verification-code|authenticator", re.I)
WANTS_PASSKEY = re.compile(r"passkey-only|webauthn-required", re.I)

# The scheme the account is handed back to. Reaching it is the end of the
# walk: there is nothing behind it to fetch, and the address is the answer.
HANDBACK = REDIRECT_URI_APP.split(":", 1)[0] + ":"

# How many hops to follow before deciding something is going in circles.
MOST_HOPS = 12

REDIRECTS = frozenset({301, 302, 303, 307, 308})

# Redirects that keep the method and the body. The rest turn into a plain GET,
# which is what a browser does and what the sign in expects.
KEEPS_METHOD = frozenset({307, 308})


def _token(page: str, what: str) -> str:
    """The verification token out of the form that asked for the fields."""
    form = FORM.search(page)
    found = TOKEN.search(form.group(1) if form else page)
    if found is None:
        raise HomeConnectAuthError(f"the {what} page carried no verification token")
    return found.group(1)


def _refused(page: str) -> None:
    """Say plainly when a sign in is one this cannot walk."""
    if WANTS_MORE.search(page):
        raise HomeConnectAuthError(
            "this account asks for a second factor, which signing in with a "
            "password here cannot answer"
        )
    if WANTS_PASSKEY.search(page):
        raise HomeConnectAuthError(
            "this account signs in with a passkey, which only a browser can do"
        )


async def _follow(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    data: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Make a request and keep going until something is not a redirect.

    Stops the moment the account is handed back to the app's own scheme.
    There is nothing there to fetch: that address is the answer.
    """
    for _ in range(MOST_HOPS):
        if url.startswith(HANDBACK):
            return url, ""
        try:
            async with session.request(
                method, url, data=data, allow_redirects=False
            ) as response:
                where = response.headers.get("location")
                if response.status in REDIRECTS and where:
                    url = urljoin(url, where)
                    if response.status not in KEEPS_METHOD:
                        method, data = "GET", None
                    continue
                return str(response.url), await response.text()
        except aiohttp.ClientError as err:
            raise HomeConnectConnectionError(f"the sign in stalled: {err}") from err
    raise HomeConnectAuthError("the sign in went round in circles")


async def sign_in(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    code_verifier: str,
    state: str,
) -> str:
    """Walk the whole sign in and come back with the one time code.

    The session wants a cookie jar of its own. SingleKey ID carries the sign
    in in cookies from the first hop to the last, and Home Assistant's shared
    session is shared with everything else.
    """
    start = auth.authorize_url(code_verifier, state, REDIRECT_URI_APP)
    where, page = await _follow(session, "GET", start)
    _LOGGER.debug("the sign in starts at %s", where.split("?")[0])
    _refused(page)

    where, page = await _follow(
        session,
        "POST",
        where,
        {EMAIL_FIELD: email, TOKEN_FIELD: _token(page, "sign in")},
    )
    _refused(page)
    if not ASKS_FOR_PASSWORD.search(page):
        # The page comes back as it went, with the address it will not take
        # still in it. There is nothing to tell one bad address from another.
        raise HomeConnectAuthError("that address was not accepted")

    where, page = await _follow(
        session,
        "POST",
        where,
        {
            PASSWORD_FIELD: password,
            REMEMBER_FIELD: "false",
            TOKEN_FIELD: _token(page, "password"),
        },
    )
    _refused(page)
    if not where.startswith(HANDBACK):
        # Still on a page of SingleKey's rather than handed back, which is
        # what a wrong password looks like from here.
        raise HomeConnectAuthError("the account would not accept that password")
    return auth.code_from(where)
