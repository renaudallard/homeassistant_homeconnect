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

"""The live connection, from bytes on the wire to events in hand."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from typing import Any

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.events import EVENTS_URL, Event, HomeConnectStream

PUSHED = (
    "event: KEEP-ALIVE\n"
    "data: \n"
    "\n"
    "event: STATUS\n"
    'data: {"items":[{"key":"BSH.Common.Status.DoorState",'
    '"value":"BSH.Common.EnumType.DoorState.Open"}]}\n'
    "id: BOSCH-WAV-1\n"
    "\n"
    "event: DISCONNECTED\n"
    "data: {}\n"
    "id: BOSCH-WAV-1\n"
    "\n"
)


@pytest.fixture
async def session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[aiohttp.ClientSession]:
    made = aioclient_mock.create_session(hass.loop)
    yield made
    await made.close()


async def test_what_arrives_is_handed_over_one_event_at_a_time(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(EVENTS_URL, text=PUSHED)
    arrived: list[Event] = []
    opened: list[bool] = []
    stream = HomeConnectStream(
        session,
        lambda: _headers(),
        lambda: 0.0,
        arrived.append,
        opened.append,
    )
    assert await stream._listen() is False
    # The keep-alive says only that the connection is there, so it is not an
    # event anybody wanted.
    assert [one.name for one in arrived] == ["STATUS", "DISCONNECTED"]
    assert arrived[0].haid == "BOSCH-WAV-1"
    assert arrived[0].items[0]["value"] == "BSH.Common.EnumType.DoorState.Open"
    assert opened == [True]


async def test_the_token_goes_out_with_the_connection(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(EVENTS_URL, text="")
    stream = HomeConnectStream(
        session, lambda: _headers(), lambda: 0.0, lambda _e: None, lambda _c: None
    )
    await stream._listen()
    sent = aioclient_mock.mock_calls[0][3]
    assert sent["Authorization"] == "Bearer a-token"
    assert sent["Accept"] == "text/event-stream"


async def test_a_refusal_that_says_how_long_to_wait_is_believed(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    from custom_components.homeconnect.events import TooSoon

    aioclient_mock.get(EVENTS_URL, status=429, headers={"Retry-After": "90"}, text="")
    stream = HomeConnectStream(
        session, lambda: _headers(), lambda: 0.0, lambda _e: None, lambda _c: None
    )
    with pytest.raises(TooSoon) as asked:
        await stream._listen()
    assert asked.value.wait == 90.0


async def test_stopping_a_stream_that_was_never_started_is_no_trouble(
    session: aiohttp.ClientSession,
) -> None:
    stream = HomeConnectStream(
        session, lambda: _headers(), lambda: 0.0, lambda _e: None, lambda _c: None
    )
    await stream.stop()


async def test_a_stream_is_started_once(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(EVENTS_URL, text="")
    spawned: list[Coroutine[Any, Any, None]] = []

    def spawn(listening: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        spawned.append(listening)
        return asyncio.get_running_loop().create_task(listening)

    stream = HomeConnectStream(
        session, lambda: _headers(), lambda: 0.0, lambda _e: None, lambda _c: None
    )
    stream.start(spawn)
    stream.start(spawn)
    assert len(spawned) == 1
    await stream.stop()


async def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer a-token", "Accept": "text/event-stream"}
