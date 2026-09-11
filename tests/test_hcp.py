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

"""Talking to an appliance directly.

The protocol half is driven against a real websocket server standing in for
an appliance, so what is checked is what actually goes over a socket rather
than what a mock was told to expect.
"""

from __future__ import annotations

import asyncio
import json
from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

import aiohttp
import pytest
from aiohttp import web

from custom_components.homeconnect.errors import HomeConnectError
from custom_components.homeconnect.hcp import CIPHERS, HcpLink, Sealed, context

KEY = urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
IV = urlsafe_b64encode(bytes(range(16))).decode().rstrip("=")


PSK = bytes(range(32))
VECTOR = bytes(range(16))


class TheirEnd(Sealed):
    """The appliance's side of the same conversation.

    The two directions are stamped differently on purpose, so a message
    cannot be replayed back the way it came. The appliance therefore signs
    with the stamp we check for, and checks for the one we sign with.
    """

    OUTWARD = Sealed.INWARD
    INWARD = Sealed.OUTWARD


def pair() -> tuple[Sealed, TheirEnd]:
    """Both ends of one conversation."""
    return Sealed(PSK, VECTOR), TheirEnd(PSK, VECTOR)


def test_a_message_comes_back_as_it_went() -> None:
    ours, theirs = pair()
    sealed = ours.seal('{"resource":"/ro/values"}')
    assert b"resource" not in sealed
    assert theirs.open(sealed) == '{"resource":"/ro/values"}'


def test_a_message_nobody_stamped_is_refused() -> None:
    ours, theirs = pair()
    sealed = ours.seal("{}")
    with pytest.raises(HomeConnectError, match="not stamped"):
        theirs.open(sealed[:-1] + bytes([sealed[-1] ^ 0xFF]))


def test_a_message_stamped_the_wrong_way_round_is_refused() -> None:
    """Which is what a message played back down the way it came looks like."""
    ours, _ = pair()
    reading = Sealed(PSK, VECTOR)
    with pytest.raises(HomeConnectError, match="not stamped"):
        reading.open(ours.seal("{}"))


def test_a_message_that_is_too_short_is_refused() -> None:
    _, theirs = pair()
    with pytest.raises(HomeConnectError, match="wrong length"):
        theirs.open(b"short")


def test_messages_have_to_arrive_in_the_order_they_were_sent() -> None:
    """Each stamp covers the one before it, so a gap cannot be read over."""
    ours, theirs = pair()
    first = ours.seal('{"one":1}')
    second = ours.seal('{"two":2}')
    with pytest.raises(HomeConnectError):
        theirs.open(second)
    assert theirs.open(first) == '{"one":1}'


def test_the_padding_is_never_nothing() -> None:
    """A message landing exactly on the block size gets a whole block of
    padding, since one byte of it would read as none at all."""
    ours, _ = pair()
    for length in range(1, 40):
        sealed = ours.seal("x" * length)
        assert (len(sealed) - Sealed.STAMP) % 16 == 0


def test_two_messages_run_one_cipher_between_them() -> None:
    """Each message continues the one before, so a replay cannot be read."""
    ours, _ = pair()
    first = ours.seal("{}")
    second = ours.seal("{}")
    assert first[: -Sealed.STAMP] != second[: -Sealed.STAMP]


class Appliance:
    """A websocket that answers the way an appliance does, encryption and all."""

    def __init__(self) -> None:
        self.heard: list[dict[str, Any]] = []
        self.ready = asyncio.Event()
        self._end = TheirEnd(PSK, VECTOR)

    async def _say(self, socket: web.WebSocketResponse, said: dict[str, Any]) -> None:
        await socket.send_bytes(self._end.seal(json.dumps(said, separators=(",", ":"))))

    async def handler(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        # The appliance opens the conversation, not the other way round.
        await self._say(
            socket,
            {
                "sID": 4242,
                "msgID": 1,
                "resource": "/ei/initialValues",
                "version": 2,
                "action": "POST",
                "data": [{"edMsgID": 77}],
            },
        )
        async for message in socket:
            if message.type is not aiohttp.WSMsgType.BINARY:
                continue
            said = json.loads(self._end.open(message.data))
            self.heard.append(said)
            if said.get("resource") == "/ro/allMandatoryValues":
                await self._say(
                    socket,
                    {
                        "sID": 4242,
                        "msgID": said["msgID"],
                        "resource": "/ro/allMandatoryValues",
                        "version": 1,
                        "action": "RESPONSE",
                        "data": [{"uid": 256, "value": 2}, {"uid": 257, "value": 5}],
                    },
                )
                self.ready.set()
        return socket


@pytest.fixture
async def appliance(socket_enabled: None) -> AsyncGenerator[tuple[Appliance, int]]:
    """One standing in, on a port of its own.

    A real server on a real socket speaking the real protocol, so what is
    checked is what actually goes over one. The harness blocks sockets by
    default, which is why this asks for them back.
    """
    pretend = Appliance()
    app = web.Application()
    app.router.add_get("/homeconnect", pretend.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # Port zero means the machine picks one, which keeps two tests running at
    # once from colliding. The site says which it got, as the address it is
    # serving on.
    port = int(urlparse(site.name).port or 0)
    yield pretend, port
    await runner.cleanup()


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    made = aiohttp.ClientSession()
    yield made
    await made.close()


def link_to(
    session: aiohttp.ClientSession,
    port: int,
    on_values: Any = None,
    on_connected: Any = None,
) -> HcpLink:
    """A link to the stand in, which encrypts the messages rather than the
    connection, that being the flavour a plain socket can carry."""
    return HcpLink(
        session,
        "127.0.0.1",
        KEY,
        IV,
        on_values or (lambda _v: None),
        on_connected or (lambda _c: None),
        port=port,
    )


def running(link: HcpLink) -> None:
    link.start(lambda coro: asyncio.get_running_loop().create_task(coro))


async def test_the_appliance_opens_and_we_take_it_up(
    appliance: tuple[Appliance, int], session: aiohttp.ClientSession
) -> None:
    pretend, port = appliance
    seen: list[dict[int, Any]] = []
    opened: list[bool] = []
    link = link_to(session, port, seen.append, opened.append)
    running(link)
    async with asyncio.timeout(10):
        await pretend.ready.wait()
        while not seen:
            await asyncio.sleep(0.01)
    await link.stop()

    said = [one["resource"] for one in pretend.heard]
    # It is told what it is talking to before anything is asked of it.
    assert said[0] == "/ei/initialValues"
    assert pretend.heard[0]["action"] == "RESPONSE"
    assert pretend.heard[0]["data"][0]["deviceType"] == "Application"
    # Then what it can do, and everything it is holding.
    assert "/ci/services" in said
    assert "/ro/allMandatoryValues" in said
    # The session and the number it handed us are carried back.
    assert pretend.heard[1]["sID"] == 4242
    assert pretend.heard[1]["msgID"] == 77
    assert seen == [{256: 2, 257: 5}]
    assert opened == [True]


async def test_setting_something_goes_by_the_number_it_goes_by(
    appliance: tuple[Appliance, int], session: aiohttp.ClientSession
) -> None:
    pretend, port = appliance
    link = link_to(session, port)
    running(link)
    async with asyncio.timeout(10):
        await pretend.ready.wait()
        await link.write(256, 1)
        while not any(one["resource"] == "/ro/values" for one in pretend.heard):
            await asyncio.sleep(0.01)
    await link.stop()

    written = next(one for one in pretend.heard if one["resource"] == "/ro/values")
    assert written["action"] == "POST"
    assert written["data"] == [{"uid": 256, "value": 1}]


async def test_writing_to_an_appliance_that_is_not_listening_says_so(
    session: aiohttp.ClientSession,
) -> None:
    link = HcpLink(session, "hob", KEY, IV, lambda _v: None, lambda _c: None)
    with pytest.raises(HomeConnectError, match="not listening"):
        await link.write(1, 1)


def test_which_way_in_follows_how_it_is_secured(
    session: aiohttp.ClientSession,
) -> None:
    """An appliance that encrypts the messages speaks plain websocket; one
    that does not secures the connection instead."""
    plain = HcpLink(session, "hob", KEY, IV, lambda _v: None, lambda _c: None)
    secured = HcpLink(session, "hob", KEY, None, lambda _v: None, lambda _c: None)
    assert plain.url == "ws://hob:80/homeconnect"
    assert secured.url == "wss://hob:443/homeconnect"
    assert (
        HcpLink(
            session, "hob", KEY, None, lambda _v: None, lambda _c: None, port=8443
        ).url
        == "wss://hob:8443/homeconnect"
    )


def test_an_appliance_found_at_an_ipv6_address_is_written_with_brackets(
    session: aiohttp.ClientSession,
) -> None:
    """The colon before the port has to be told from the colons in the
    address. Without the brackets it is a different address rather than a
    malformed one, so the connection is simply made to the wrong place."""
    six = "fd74:8e83:4254:c6b0:9627:70ff:fe84:7dcd"
    assert (
        HcpLink(session, six, KEY, None, lambda _v: None, lambda _c: None).url
        == f"wss://[{six}]:443/homeconnect"
    )
    assert (
        HcpLink(session, six, KEY, IV, lambda _v: None, lambda _c: None).url
        == f"ws://[{six}]:80/homeconnect"
    )
    # An address that is not one of those is left as it is.
    assert (
        HcpLink(session, "172.20.0.209", KEY, IV, lambda _v: None, lambda _c: None).url
        == "ws://172.20.0.209:80/homeconnect"
    )


def test_the_offer_is_the_two_suites_the_app_offers() -> None:
    """An appliance takes the first of these and refuses anything that does
    not agree a fresh secret first, so the pair is offered and nothing else.
    """
    made = context(PSK)
    offered = [
        one["name"] for one in made.get_ciphers() if one["name"].startswith("ECDHE-PSK")
    ]
    assert offered == CIPHERS.split(":")
    # Only the shared key suites, and only the version they belong to.
    assert not [one for one in made.get_ciphers() if one["name"].startswith("PSK-")]
    assert made.minimum_version is made.maximum_version


async def test_what_is_said_is_read_out_of_either_kind_of_frame(
    session: aiohttp.ClientSession,
) -> None:
    """An appliance that secures the connection rather than the messages
    speaks in text. Bytes saying the same thing are read too, because which
    frame they came in says nothing about what they mean, and passing one
    over loses the whole conversation rather than the one message."""
    seen: list[dict[int, Any]] = []
    link = HcpLink(session, "hob", KEY, None, seen.append, lambda _c: None)
    said = json.dumps(
        {
            "sID": 1,
            "msgID": 1,
            "resource": "/ro/values",
            "version": 1,
            "action": "NOTIFY",
            "data": [{"uid": 256, "value": 3}],
        }
    )
    await link._heard(
        aiohttp.WSMessage(type=aiohttp.WSMsgType.TEXT, data=said, extra=None)
    )
    await link._heard(
        aiohttp.WSMessage(type=aiohttp.WSMsgType.BINARY, data=said.encode(), extra=None)
    )
    assert seen == [{256: 3}, {256: 3}]


async def test_a_frame_holding_nothing_readable_is_passed_over(
    session: aiohttp.ClientSession,
) -> None:
    seen: list[dict[int, Any]] = []
    link = HcpLink(session, "hob", KEY, None, seen.append, lambda _c: None)
    for message in (
        aiohttp.WSMessage(type=aiohttp.WSMsgType.BINARY, data=b"\xff\xfe", extra=None),
        aiohttp.WSMessage(type=aiohttp.WSMsgType.PING, data=b"", extra=None),
    ):
        await link._heard(message)
    assert seen == []


async def test_a_quiet_appliance_is_asked_after_rather_than_cut_off(
    appliance: tuple[Appliance, int], session: aiohttp.ClientSession
) -> None:
    """An appliance with nothing to report says nothing at all, for as long
    as an hour. Noticing one that has gone away is the ping's work, so the
    read is only there to catch a socket that has wedged."""
    from custom_components.homeconnect.hcp import PING, SILENCE

    assert SILENCE > PING * 4
    pretend, port = appliance
    link = link_to(session, port)
    running(link)
    async with asyncio.timeout(10):
        await pretend.ready.wait()
    assert link.talking
    await link.stop()
