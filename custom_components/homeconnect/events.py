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

"""Live updates pushed by the cloud.

Polling means a cycle can finish minutes before anyone hears about it, and the
API counts every call against a quota, so asking often is not an option. The
cloud will push instead, over one long lived connection carrying every
appliance on the account.

What arrives is Server-Sent Events: a name, a body and the appliance it is
about, separated by blank lines. Nothing here interprets them; that belongs
with whatever holds the state they change.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import API_HOST, API_PATH, STREAM_READ_TIMEOUT

_LOGGER = logging.getLogger(__name__)

EVENTS_URL = f"{API_HOST}{API_PATH}/homeappliances/events"

RECONNECT_DELAY = 5.0
# Something is wrong rather than merely unlucky, so wait longer.
RECONNECT_DELAY_UNEXPECTED = 30.0
# However close a token is to expiring, hold the connection this long, so a
# clock that has gone wrong cannot turn the stream into a reconnect loop.
MINIMUM_LIFE = 60.0
# Longest the cloud is ever asked to wait for, whatever it says. A service
# that answers a refusal with an hour would otherwise leave the account with
# no live updates and no explanation for as long as it liked.
LONGEST_WAIT = 300.0

# The one event that says nothing except that the connection is still there.
KEEP_ALIVE = "KEEP-ALIVE"

# How the caller makes a task of the listening. Home Assistant wants to know
# about the ones a config entry owns, and nothing else in here knows that Home
# Assistant exists.
Spawn = Callable[[Coroutine[Any, Any, None]], "asyncio.Task[None]"]


@dataclass(frozen=True)
class Event:
    """One thing the cloud said happened."""

    name: str
    haid: str
    data: dict[str, Any]

    @property
    def items(self) -> list[dict[str, Any]]:
        """The values that changed, which is what most events carry."""
        found = self.data.get("items")
        if not isinstance(found, list):
            return []
        return [item for item in found if isinstance(item, dict)]


def parse(block: list[str]) -> Event | None:
    """One event out of the lines between two blank ones.

    A field is a name, a colon and a value with one optional space after it.
    Data can be given over several lines, which are joined with newlines
    between them the way the format says. A block with no name is not an
    event, and neither is a comment, which is what a line with no name at all
    is for.
    """
    name = ""
    haid = ""
    body: list[str] = []
    for line in block:
        field, _, value = line.partition(":")
        if not field:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            name = value
        elif field == "id":
            haid = value
        elif field == "data":
            body.append(value)
    if not name:
        return None
    joined = "\n".join(body)
    if not joined:
        return Event(name, haid, {})
    try:
        loaded = json.loads(joined)
    except ValueError:
        _LOGGER.debug("a %s event arrived with a body that is not JSON", name)
        return None
    return Event(name, haid, loaded if isinstance(loaded, dict) else {})


class HomeConnectStream:
    """Watches one account's appliances for as long as it is running."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        headers: Callable[[], Any],
        renew_after: Callable[[], float],
        on_event: Callable[[Event], None],
        on_connected: Callable[[bool], None],
    ) -> None:
        self._session = session
        self._headers = headers
        self._renew_after = renew_after
        self._on_event = on_event
        self._on_connected = on_connected
        self._task: asyncio.Task[None] | None = None
        # Whether the last failure has already been written out in full.
        self._complained = False
        # Whether the last attempt got as far as an open connection.
        self._opened = False

    def start(self, spawn: Spawn) -> None:
        if self._task is None:
            self._task = spawn(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            delay = RECONNECT_DELAY
            self._opened = False
            # Whether what ended the connection was our own doing.
            planned = False
            try:
                if await self._listen():
                    # It ended because the token was running out, which is
                    # not a reason to wait before opening another.
                    planned = True
                    delay = 0.0
            except asyncio.CancelledError:
                # Being stopped is not the stream dropping, and whatever is
                # stopping it does not want to hear that it has.
                raise
            except aiohttp.ClientError as err:
                _LOGGER.debug("the event stream dropped: %s", err)
                if not self._opened:
                    # Nothing dropped, because nothing opened. A token the
                    # cloud will not take is refused again just as surely in
                    # thirty seconds as in five.
                    delay = RECONNECT_DELAY_UNEXPECTED
            except TooSoon as err:
                delay = err.wait
                _LOGGER.debug("the cloud asked for %d seconds before reopening", delay)
            except Exception:
                # A stream that is never going to work would otherwise write a
                # traceback every half minute for as long as the entry is
                # loaded. The first one says what is wrong and the rest only
                # say it again, so they go to debug.
                if self._complained:
                    _LOGGER.debug("the event stream failed again", exc_info=True)
                else:
                    _LOGGER.exception("the event stream failed unexpectedly")
                    self._complained = True
                delay = RECONNECT_DELAY_UNEXPECTED
            if not planned:
                # Closing a connection to open it with a fresh token is not
                # the stream dropping. Saying it was puts the account back on
                # being asked every half minute until something is pushed,
                # which on a quiet appliance is a long time to ask for nothing.
                self._on_connected(False)
            if delay:
                await asyncio.sleep(delay)

    async def _listen(self) -> bool:
        """Listen until the connection ends. True if the token ran it out.

        A connection is opened with a token and keeps it for as long as it
        lives, so it is closed and opened again before that token expires.
        Waiting for the cloud to object would mean trusting it to notice, and
        a stream that is quietly ignored looks exactly like a quiet account.
        """
        headers = await self._headers()
        renew_in = max(MINIMUM_LIFE, self._renew_after())
        # No total, because the whole point is a connection that lasts. Silence
        # is what a dead connection looks like, so that is what is timed.
        timeout = aiohttp.ClientTimeout(total=None, sock_read=STREAM_READ_TIMEOUT)
        async with self._session.get(
            EVENTS_URL, headers=headers, timeout=timeout
        ) as response:
            if response.status == 429:
                raise TooSoon(_wait_from(response.headers.get("Retry-After")))
            response.raise_for_status()
            _LOGGER.debug("listening for the next %d seconds", renew_in)
            # It opened, so the next thing to go wrong is worth reading, and
            # whatever ends it is a connection dropping rather than one the
            # cloud would not give us.
            self._complained = False
            self._opened = True
            self._on_connected(True)
            try:
                async with asyncio.timeout(renew_in):
                    await self._read(response)
            except TimeoutError:
                _LOGGER.debug("reopening the event stream before the token expires")
                return True
        return False

    async def _read(self, response: aiohttp.ClientResponse) -> None:
        """Turn the bytes coming in into events, one blank line at a time.

        Read in whatever sizes the network hands over rather than a line at a
        time, because a line is only as long as the cloud feels like making it
        and a reader with a limit would drop the connection over a long one.
        """
        pending = b""
        block: list[str] = []
        async for chunk in response.content.iter_any():
            pending += chunk
            while b"\n" in pending:
                raw, _, pending = pending.partition(b"\n")
                line = raw.rstrip(b"\r").decode("utf-8", "replace")
                if line:
                    block.append(line)
                    continue
                event = parse(block)
                block = []
                if event is not None and event.name != KEEP_ALIVE:
                    self._on_event(event)


class TooSoon(Exception):
    """The cloud refused a connection and said how long to wait."""

    def __init__(self, wait: float) -> None:
        super().__init__(f"asked to wait {wait} seconds")
        self.wait = wait


def _wait_from(given: str | None) -> float:
    """How long to wait before opening the stream again.

    Anything unreadable, and anything longer than we are prepared to go
    without updates, comes back as the ordinary wait for something unexpected.
    """
    try:
        asked = float(given or "")
    except ValueError:
        return RECONNECT_DELAY_UNEXPECTED
    return min(max(asked, RECONNECT_DELAY_UNEXPECTED), LONGEST_WAIT)
