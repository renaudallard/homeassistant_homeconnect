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

"""The appliance half of the Home Connect API.

Everything here needs an access token, so the client owns the token pair and
renews it when it goes stale. Renewal rotates the refresh token, and a caller
that does not store the new one locks itself out, so the client reports every
new pair through a listener.

The API answers every question with the same envelope: an object with one
member called data, holding either the thing that was asked for or a list
under a name of its own. Unwrapping that is the only shape knowledge in here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from . import auth, http
from .auth import Tokens
from .const import (
    API_HOST,
    API_PATH,
    DESCRIPTION_PATH,
    ENCRYPTION_PATH,
    MEDIA_TYPE,
    SERVICES_HOSTS,
    TOKEN_EXPIRY_MARGIN,
)
from .errors import (
    HomeConnectAuthError,
    HomeConnectConnectionError,
    HomeConnectError,
    HomeConnectRefused,
    HomeConnectTooManyRequests,
)
from .http import failure, hidden_id, redact_url

_LOGGER = logging.getLogger(__name__)

# A description is a zip of a few hundred kilobytes, which is longer than an
# ordinary call but not longer than a wait anybody would sit through.
FETCH = aiohttp.ClientTimeout(total=60.0, connect=10.0)

TokenListener = Callable[[Tokens], Awaitable[None]]

# Which of the two programme slots a call is about. One is what the appliance
# is doing and the other is what it is set to do next, and every call that
# touches a programme takes one or the other.
ACTIVE = "active"
SELECTED = "selected"


def _members(payload: Any, named: str) -> list[dict[str, Any]]:
    """The list an answer carries, whatever else came with it.

    An answer with nothing in it is a real answer: an appliance that has no
    settings it will admit to says so with an empty list, and reading that as
    a failure would take away the entities of every other appliance on the
    account along with it.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise HomeConnectConnectionError(f"the cloud returned no {named}")
    found = data.get(named)
    if found is None:
        return []
    if not isinstance(found, list):
        raise HomeConnectConnectionError(f"the cloud returned no list of {named}")
    return [member for member in found if isinstance(member, dict)]


def _object(payload: Any, named: str) -> dict[str, Any]:
    """The single thing an answer carries."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise HomeConnectConnectionError(f"the cloud returned no {named}")
    return data


class HomeConnectApi:
    """Reads appliance state and sends commands."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens,
        language: str,
        on_tokens: TokenListener | None = None,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._language = language
        self._on_tokens = on_tokens
        self._lock = asyncio.Lock()
        # Which half of the world the cloud says it answered from. It says so
        # in a header on every answer, which is better than guessing at the
        # account service later.
        self._env: str | None = None

    @property
    def region(self) -> str | None:
        """Which regional service this account belongs to, where it has said.

        The cloud stamps every answer with the environment it came from, as
        in EU-PRD, and the first word of that is the region. It is only ever
        a hint: it decides which service host to try first, and being wrong
        costs one refused call rather than a failure.
        """
        if not self._env:
            return None
        return self._env.split("-", 1)[0].lower()

    @property
    def tokens(self) -> Tokens:
        """The current token pair, which changes on every renewal."""
        return self._tokens

    def seconds_until_renewal(self) -> float:
        """How long the token in hand is good for, less the margin.

        The event stream holds one connection open for as long as it is
        allowed to, so it has to know when the token it opened with stops
        being worth anything.
        """
        return max(0.0, self._tokens.expires_at - TOKEN_EXPIRY_MARGIN - time.time())

    async def headers(self, accept: str = MEDIA_TYPE) -> dict[str, str]:
        """What every call carries, with a token that is good right now.

        The language decides what the cloud calls a programme and the values
        of a setting, which is the only reason it is sent: nothing here reads
        an answer by its text.
        """
        return {
            "Authorization": f"Bearer {await self._access_token()}",
            "Accept": accept,
            "Accept-Language": self._language,
        }

    async def _store(self, tokens: Tokens) -> None:
        self._tokens = tokens
        if self._on_tokens is not None:
            await self._on_tokens(tokens)

    async def _access_token(self) -> str:
        async with self._lock:
            if self._tokens.expired:
                try:
                    await self._store(await auth.renew(self._session, self._tokens))
                except HomeConnectTooManyRequests:
                    # Renewing a token that was issued moments ago is refused.
                    # The one in hand is good until it actually expires, so use
                    # it rather than failing an update over the margin.
                    if not self._tokens.usable:
                        raise
                    _LOGGER.debug("renewal refused as too soon, keeping the token")
            return self._tokens.access_token

    async def _renew(self, rejected: str) -> None:
        """Renew a token the service turned down, unless someone beat us to it."""
        async with self._lock:
            if self._tokens.access_token != rejected:
                return
            await self._store(await auth.renew(self._session, self._tokens))

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> tuple[int, Any]:
        """Make one call, renewing the token once if it is refused as stale."""
        token = await self._access_token()
        url = f"{API_HOST}{API_PATH}{path}"
        headers = await self.headers()
        if json_body is not None:
            headers["Content-Type"] = MEDIA_TYPE
        status, payload, answered = await http.request(
            self._session, method, url, headers=headers, json_body=json_body
        )
        if answered.get("hc-env"):
            self._env = answered["hc-env"]
        if status == 401 and retry:
            # The token was refused early. Renew once and try again, so a clock
            # that drifted or a token revoked server side does not surface as a
            # failed update.
            await self._renew(token)
            return await self._call(method, path, json_body=json_body, retry=False)
        if status == 429:
            after = answered.get("retry-after")
            raise HomeConnectTooManyRequests(
                f"{redact_url(url)} asked us to slow down",
                float(after) if after and after.isdigit() else None,
            )
        if status in (401, 403):
            raise HomeConnectAuthError(
                f"{redact_url(url)} rejected the access token ({status})"
            )
        if status == 409:
            key, described = failure(payload)
            raise HomeConnectRefused(described, key)
        return status, payload

    async def _get(self, path: str, named: str) -> list[dict[str, Any]]:
        """Read a list, or nothing at all where the appliance will not say.

        An appliance that has never had a programme running answers the active
        programme with a 404 rather than with an empty answer, and one that
        cannot run programmes at all answers the whole of that part of the API
        the same way. One that is switched off refuses the question outright,
        because what it will run depends on a state it is not in. None of the
        three is a failure, and all three mean the same thing here: there is
        nothing to be had at the moment.
        """
        status, payload = await self._read(path)
        if status == 404:
            return []
        self._expect_ok(status, payload, path)
        return _members(payload, named)

    async def _get_one(self, path: str, named: str) -> dict[str, Any] | None:
        """Read a single thing, or nothing where the appliance will not say."""
        status, payload = await self._read(path)
        if status == 404:
            return None
        self._expect_ok(status, payload, path)
        return _object(payload, named)

    async def _read(self, path: str) -> tuple[int, Any]:
        """Ask a question, taking a refusal for an answer.

        Only reading works this way. A refusal to do something is worth
        passing on to whoever asked for it; a refusal to say something is the
        appliance saying there is nothing to say, and putting that in front of
        the user as an error would take the whole account down every time an
        oven was switched off at the wall.
        """
        try:
            return await self._call("GET", path)
        except HomeConnectRefused as refused:
            _LOGGER.debug("%s would not answer: %s", redact_url(path), refused)
            return 404, None

    def _expect_ok(self, status: int, payload: Any, path: str) -> None:
        if status >= 400:
            _, described = failure(payload)
            raise HomeConnectConnectionError(
                f"{redact_url(path)} refused the request ({status}): {described}"
            )

    async def _put(self, path: str, key: str, value: Any) -> None:
        """Set one thing, which is how every value on an appliance is set."""
        status, payload = await self._call(
            "PUT", path, json_body={"data": {"key": key, "value": value}}
        )
        self._expect_ok(status, payload, path)

    # What is on the account

    async def appliances(self) -> list[dict[str, Any]]:
        """Every appliance paired with the account."""
        status, payload = await self._call("GET", "/homeappliances")
        self._expect_ok(status, payload, "/homeappliances")
        return _members(payload, "homeappliances")

    # What one appliance is and what it is doing

    async def status(self, haid: str) -> list[dict[str, Any]]:
        """What the appliance reports about itself and will not let us change."""
        return await self._get(f"/homeappliances/{haid}/status", "status")

    async def settings(self, haid: str) -> list[dict[str, Any]]:
        """The settings the appliance has, by name only.

        The list says nothing about what each one accepts. That is what the
        call below is for, and it is why reading an appliance in full costs a
        call for every setting it has.
        """
        return await self._get(f"/homeappliances/{haid}/settings", "settings")

    async def setting(self, haid: str, key: str) -> dict[str, Any] | None:
        """One setting, with the values or the range it will take."""
        return await self._get_one(f"/homeappliances/{haid}/settings/{key}", "setting")

    async def commands(self, haid: str) -> list[dict[str, Any]]:
        """What the appliance can be told to do, beyond running a programme."""
        return await self._get(f"/homeappliances/{haid}/commands", "commands")

    async def events(self, haid: str) -> list[dict[str, Any]]:
        """What the appliance is currently complaining about.

        The same address serves the live stream and, asked for as ordinary
        JSON, what is going on at this moment. That second form is the only
        way to learn about a rinse aid that ran out while Home Assistant was
        not listening, so it is what a fresh look reads.

        It answers in a shape of its own, with the items at the top rather
        than under data, and has been seen wrapped the ordinary way as well.
        Both are read, because an appliance with nothing to complain about and
        one whose answer we cannot read look far too much alike.
        """
        path = f"/homeappliances/{haid}/events"
        status, payload = await self._read(path)
        if status == 404:
            return []
        self._expect_ok(status, payload, path)
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
        return _members(payload, "items")

    # Programmes

    async def available_programs(self, haid: str) -> list[dict[str, Any]]:
        """The programmes the appliance will run in the state it is in.

        This moves: an appliance that is switched off, or whose door is open,
        offers nothing at all, and one mid-cycle offers only what it is doing.
        """
        return await self._get(f"/homeappliances/{haid}/programs/available", "programs")

    async def program_options(self, haid: str, program: str) -> list[dict[str, Any]]:
        """What one programme can be adjusted by, and within what limits."""
        found = await self._get_one(
            f"/homeappliances/{haid}/programs/available/{program}", "program"
        )
        if found is None:
            return []
        options = found.get("options")
        return (
            [option for option in options if isinstance(option, dict)]
            if isinstance(options, list)
            else []
        )

    async def program(self, haid: str, which: str) -> dict[str, Any] | None:
        """The programme in one of the two slots, or nothing if it is empty."""
        return await self._get_one(
            f"/homeappliances/{haid}/programs/{which}", "program"
        )

    async def set_program(
        self, haid: str, which: str, key: str, options: list[dict[str, Any]]
    ) -> None:
        """Put a programme in one of the two slots.

        Putting one in the active slot starts it. Putting one in the selected
        slot only sets it up, which is the safer half of the same call and the
        only one an appliance will take while it is running.
        """
        path = f"/homeappliances/{haid}/programs/{which}"
        status, payload = await self._call(
            "PUT", path, json_body={"data": {"key": key, "options": options}}
        )
        self._expect_ok(status, payload, path)

    async def stop_program(self, haid: str) -> None:
        """Stop whatever the appliance is doing."""
        path = f"/homeappliances/{haid}/programs/active"
        status, payload = await self._call("DELETE", path)
        self._expect_ok(status, payload, path)

    # Setting things

    async def set_setting(self, haid: str, key: str, value: Any) -> None:
        """Change one of the appliance's own settings."""
        await self._put(f"/homeappliances/{haid}/settings/{key}", key, value)

    async def set_option(self, haid: str, which: str, key: str, value: Any) -> None:
        """Change one option of the programme in one of the two slots."""
        await self._put(
            f"/homeappliances/{haid}/programs/{which}/options/{key}", key, value
        )

    async def fetch(self, url: str, binary: bool = False) -> Any:
        """Read something from outside the appliance API.

        The account's own service is a different host with a different shape,
        and one of the two things wanted from it is a zip rather than JSON.
        Everything else about a call is the same, so only the reading of the
        answer differs.
        """
        headers = await self.headers("*/*" if binary else "application/json")
        try:
            async with self._session.get(url, headers=headers, timeout=FETCH) as answer:
                body = await answer.read()
                status = answer.status
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeConnectConnectionError(
                f"{redact_url(url)} is unreachable: {err}"
            ) from err
        _LOGGER.debug("GET %s <- %s, %d bytes", redact_url(url), status, len(body))
        if status in (401, 403):
            raise HomeConnectAuthError(
                f"{redact_url(url)} rejected the access token ({status})"
            )
        if status >= 400:
            raise HomeConnectConnectionError(
                f"{redact_url(url)} refused the request ({status})"
            )
        if binary:
            return body
        try:
            return json.loads(body) if body else None
        except ValueError as err:
            raise HomeConnectConnectionError(
                f"{redact_url(url)} answered with something that is not JSON"
            ) from err

    async def send_command(self, haid: str, key: str) -> None:
        """Tell the appliance to do something once.

        Every one of these is a flag that only ever goes true. There is no
        turning a command off again, so the value never varies.
        """
        await self._put(f"/homeappliances/{haid}/commands/{key}", key, True)


class HomeConnectAccount:
    """The account's own service, which is not the appliance API.

    Two things live here and nowhere else: the key that lets this talk to an
    appliance directly, and the appliance's own description of itself. Both
    are wanted once and then kept, so this is deliberately separate from the
    client that does the minute to minute work.
    """

    def __init__(self, api: HomeConnectApi) -> None:
        self._api = api
        # Which half of the world this account belongs to, once it is known.
        self._host: str | None = None

    async def _fetch(self, path: str, binary: bool = False) -> Any:
        """Ask each service host in turn until one of them answers.

        An account belongs to one region and the other will not have heard of
        it. Which is which is not something the account says in advance, so
        the one that answers is the answer, and it is remembered.
        """
        hosts = [self._host] if self._host else _in_order(self._api.region)
        last: Exception | None = None
        for host in hosts:
            try:
                found = await self._api.fetch(f"{host}{path}", binary=binary)
            except HomeConnectAuthError:
                raise
            except HomeConnectError as err:
                _LOGGER.debug("%s did not answer for %s: %s", host, path, err)
                last = err
                continue
            self._host = host
            return found
        raise last or HomeConnectConnectionError(f"nothing answered for {path}")

    async def keys(self, haids: list[str]) -> dict[str, dict[str, str]]:
        """The key each appliance is reached directly with, by appliance.

        Each appliance is asked for on its own, that being where its key is
        kept. One that has none is left out rather than stopping the rest,
        since an appliance without a key says nothing about the next one.
        What came back is described to the log when it holds no key, because
        a shape nobody here has seen is the one thing a report about this
        cannot do without.
        """
        found: dict[str, dict[str, str]] = {}
        for haid in haids:
            try:
                answer = await self._fetch(ENCRYPTION_PATH.format(haid))
            except HomeConnectAuthError:
                # The token is the account's rather than the appliance's, so
                # being refused once is being refused for all of them, and
                # signing in again is the only way out of it.
                raise
            except HomeConnectError as err:
                _LOGGER.debug("no key to be had for %s: %s", hidden_id(haid), err)
                continue
            secured = _key_in(answer)
            if secured is None:
                _LOGGER.debug("the key for one appliance is shaped %s", shape(answer))
                continue
            found[haid] = secured
        return found

    async def description(self, haid: str) -> bytes:
        """One appliance's description of itself, as it was sent."""
        found = await self._fetch(DESCRIPTION_PATH.format(haid), binary=True)
        if not isinstance(found, bytes):
            raise HomeConnectConnectionError("the description came back empty")
        return found


# How an appliance is secured. One of the two is filled in and the other is
# null: the key alone means the connection is secured, and a starting vector
# beside it means the messages are.
TLS = "tls"
AES = "aes"


def _in_order(region: str | None) -> list[str]:
    """The service hosts, likeliest first.

    The cloud says which region answered, so the host for that region is
    tried before the other. Where it has not said, or says something nobody
    here has seen, they are tried in the order they are written.
    """
    hosts = list(SERVICES_HOSTS)
    if region:
        hosts.sort(key=lambda host: f"//{region}." not in host)
    return hosts


# How deep to describe an answer, and how many members of one thing to name.
# A description is for reading, and one that runs to pages is not read.
DEEPEST = 6
WIDEST = 40


def shape(payload: Any, depth: int = 0) -> str:
    """What an answer is made of, without any of what it says.

    Only the names of the members and the kinds of the values, so that an
    answer in a shape nobody here has seen can be described in a bug report
    without any of it being anybody's business but theirs.
    """
    if depth >= DEEPEST:
        return "..."
    if isinstance(payload, dict):
        inside = ", ".join(
            f"{name}: {shape(value, depth + 1)}"
            for name, value in list(payload.items())[:WIDEST]
        )
        return "{" + inside + "}"
    if isinstance(payload, list):
        if not payload:
            return "[]"
        return f"[{shape(payload[0], depth + 1)}] x{len(payload)}"
    if payload is None:
        return "null"
    return type(payload).__name__


def _key_in(payload: Any) -> dict[str, str] | None:
    """The key one appliance is reached with, out of its own answer.

    One of the two ways of securing it is filled in and the other is null.
    The key on its own means the connection is secured; a starting vector
    beside it means the messages are.
    """
    if not isinstance(payload, dict):
        return None
    secured = payload.get(TLS) or payload.get(AES)
    if not isinstance(secured, dict) or not secured.get("key"):
        return None
    return {
        "key": str(secured["key"]),
        **({"iv": str(secured["iv"])} if secured.get("iv") else {}),
    }
