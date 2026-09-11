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

"""Talking to an appliance directly, over the network it is already on.

An appliance answers on a websocket of its own, at /homeconnect, and secures
it in one of two ways. The newer sort speaks TLS with a shared key instead of
a certificate, on port 443. The older sort speaks plain websocket on port 80
and encrypts each message itself, chaining the cipher and a running digest
from one message to the next so that a replayed or reordered one is refused.

Which of the two an appliance is, and the key either needs, comes from the
account rather than from the appliance: there is nothing on the network that
would let a stranger in. That is fetched once and kept.

What travels is JSON: a session, a running message number, a resource, and
what is being done to it. Values are numbers on both sides, which is what the
appliance's description file is for.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from base64 import urlsafe_b64decode
from collections.abc import Callable, Coroutine
from hashlib import sha256
from hmac import HMAC
from hmac import compare_digest as same
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .errors import HomeConnectConnectionError, HomeConnectError

_LOGGER = logging.getLogger(__name__)

PATH = "/homeconnect"
TLS_PORT = 443
PLAIN_PORT = 80

# What the app offers, in the order it offers it. Asking for the same two
# means an appliance that will not do the first is still reachable, and
# nothing outside the pair is asked for: a hob refuses the shared key suites
# that do not agree a fresh secret first, so offering them is only noise.
CIPHERS = "ECDHE-PSK-CHACHA20-POLY1305:ECDHE-PSK-AES128-CBC-SHA256"

# The resources a conversation is made of. Only a few are of any use here: the
# appliance opens with one, and the rest are what it will say about itself.
INITIAL = "/ei/initialValues"
READY = "/ei/deviceReady"
SERVICES = "/ci/services"
AUTHENTICATION = "/ci/authentication"
VALUES = "/ro/values"
EVERYTHING = "/ro/allMandatoryValues"
DESCRIPTIONS = "/ro/allDescriptionChanges"
ACTIVE = "/ro/activeProgram"
SELECTED = "/ro/selectedProgram"

GET = "GET"
POST = "POST"
NOTIFY = "NOTIFY"
RESPONSE = "RESPONSE"

RECONNECT_DELAY = 5.0
RECONNECT_DELAY_UNEXPECTED = 30.0
# An appliance that says nothing for this long is one that has gone away
# without saying so.
SILENCE = 120.0

Spawn = Callable[[Coroutine[Any, Any, None]], "asyncio.Task[None]"]


def _key(written: str) -> bytes:
    """A key as the account writes them, which is URL safe and unpadded."""
    try:
        return urlsafe_b64decode(written + "=" * (-len(written) % 4))
    except (ValueError, TypeError) as err:
        raise HomeConnectError(f"the appliance key does not read: {err}") from err


class Sealed:
    """Messages for an appliance that encrypts them itself.

    Both directions run one cipher for the whole conversation rather than one
    per message, and each message carries a digest over the one before it. So
    the state has to be thrown away and built again whenever the connection
    is, and a message that arrives out of order cannot be read at all, which
    is the point of it.
    """

    # How much of the digest travels, and what each direction is called in it.
    STAMP = 16
    OUTWARD = b"\x45"
    INWARD = b"\x43"

    def __init__(self, psk: bytes, iv: bytes) -> None:
        self._iv = iv
        self._encryption = HMAC(psk, b"ENC", sha256).digest()
        self._signing = HMAC(psk, b"MAC", sha256).digest()
        self.reset()

    def reset(self) -> None:
        """Start again, which is what a fresh connection is."""
        self._sent = bytes(self.STAMP)
        self._received = bytes(self.STAMP)
        aes = Cipher(algorithms.AES(self._encryption), modes.CBC(self._iv))
        self._out = aes.encryptor()
        self._in = aes.decryptor()

    def _stamp(self, direction: bytes, last: bytes, body: bytes) -> bytes:
        return HMAC(self._signing, self._iv + direction + last + body, sha256).digest()[
            : self.STAMP
        ]

    def seal(self, message: str) -> bytes:
        """One message, encrypted and stamped.

        The padding is the length of itself in the last byte and noise in
        between, and a message that already lands on the block size gets a
        whole block of it rather than one byte that would read as none.
        """
        plain = message.encode("utf-8")
        length = 16 - (len(plain) % 16)
        if length == 1:
            length += 16
        plain += b"\x00" + secrets.token_bytes(length - 2) + bytes([length])
        body = self._out.update(plain)
        self._sent = self._stamp(self.OUTWARD, self._sent, body)
        return body + self._sent

    def open(self, buffer: bytes) -> str:
        """One message, checked and decrypted."""
        if len(buffer) < 32 or len(buffer) % 16 != self.STAMP % 16:
            raise HomeConnectError("a message arrived the wrong length")
        body, stamp = buffer[: -self.STAMP], buffer[-self.STAMP :]
        if not same(stamp, self._stamp(self.INWARD, self._received, body)):
            raise HomeConnectError("a message arrived that was not stamped by us")
        self._received = stamp
        plain = self._in.update(body)
        padding = plain[-1] if plain else 0
        if not 0 < padding <= len(plain):
            raise HomeConnectError("a message arrived padded to no length")
        return plain[:-padding].decode("utf-8", "replace")


def context(psk: bytes) -> Any:
    """A TLS setup that proves itself with a shared key rather than a name.

    There is no certificate to check and no name to check it against: both
    ends already know the secret, which is what the handshake proves. So the
    usual checks are turned off because there is nothing for them to look at,
    not because they are inconvenient.
    """
    import ssl

    made = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    made.check_hostname = False
    made.verify_mode = ssl.CERT_NONE
    # The shared key suites are all TLS 1.2. Offering 1.3 as well only invites
    # a handshake the appliance cannot finish.
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    made.maximum_version = ssl.TLSVersion.TLSv1_2
    made.set_ciphers(CIPHERS)
    made.set_psk_client_callback(lambda hint: (None, psk))
    return made


def _written(host: str) -> str:
    """A host as it goes into an address.

    An IPv6 address is written with brackets round it, so that the colon
    before the port can be told from the colons in the address itself. An
    address without brackets is a different address, not a malformed one, so
    nothing complains: the connection is simply made to the wrong place.
    """
    return f"[{host}]" if ":" in host else host


class HcpLink:
    """One appliance, talked to directly, for as long as it will answer.

    The appliance opens the conversation rather than being asked to: the first
    thing it sends carries the session and the number the next message must
    have, and nothing can be asked of it before that arrives.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        key: str,
        iv: str | None,
        on_values: Callable[[dict[int, Any]], None],
        on_connected: Callable[[bool], None],
        identifier: str = "homeassistant",
        port: int | None = None,
    ) -> None:
        self._session = session
        self._host = host
        # An appliance names the port it listens on in the record it shouts,
        # so where that is known it is used rather than assumed.
        self._port = port
        self._psk = _key(key)
        # An appliance that sends its own starting vector is one that encrypts
        # the messages rather than the connection.
        self._sealed = Sealed(self._psk, _key(iv)) if iv else None
        self._on_values = on_values
        self._on_connected = on_connected
        self._identifier = identifier
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._sid: int | None = None
        self._msgid = 0
        self._task: asyncio.Task[None] | None = None
        self._complained = False

    @property
    def url(self) -> str:
        scheme = "ws" if self._sealed else "wss"
        usual = PLAIN_PORT if self._sealed else TLS_PORT
        return f"{scheme}://{_written(self._host)}:{self._port or usual}{PATH}"

    @property
    def talking(self) -> bool:
        """Whether there is a conversation to say anything into."""
        return self._socket is not None and not self._socket.closed

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
            try:
                await self._talk()
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, HomeConnectError, OSError) as err:
                _LOGGER.debug("%s stopped talking: %s", self._host, err)
                delay = RECONNECT_DELAY_UNEXPECTED
            except Exception:
                # An appliance that is never going to answer would otherwise
                # write a traceback every half minute for as long as the entry
                # is loaded. The first one says what is wrong.
                if self._complained:
                    _LOGGER.debug("%s failed again", self._host, exc_info=True)
                else:
                    _LOGGER.exception("%s failed unexpectedly", self._host)
                    self._complained = True
                delay = RECONNECT_DELAY_UNEXPECTED
            finally:
                self._socket = None
                self._sid = None
            self._on_connected(False)
            await asyncio.sleep(delay)

    async def _talk(self) -> None:
        """One conversation, from opening the socket to it going quiet."""
        if self._sealed is not None:
            self._sealed.reset()
        settings: dict[str, Any] = {"headers": {"Origin": ""}}
        if self._sealed is None:
            settings["ssl"] = context(self._psk)
        _LOGGER.debug("opening %s", self.url)
        async with self._session.ws_connect(
            self.url, heartbeat=None, **settings
        ) as socket:
            self._socket = socket
            self._complained = False
            while True:
                async with asyncio.timeout(SILENCE):
                    message = await socket.receive()
                # Every frame, so that a conversation going quiet can be told
                # from one whose frames are arriving and being passed over.
                _LOGGER.debug(
                    "%s sent %s, %d bytes",
                    self._host,
                    message.type.name,
                    len(message.data) if isinstance(message.data, (str, bytes)) else 0,
                )
                if message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    return
                if message.type is aiohttp.WSMsgType.ERROR:
                    raise aiohttp.ClientError("the appliance reported an error")
                await self._heard(message)

    async def _heard(self, message: aiohttp.WSMessage) -> None:
        if self._sealed is not None:
            if message.type is not aiohttp.WSMsgType.BINARY:
                _LOGGER.debug("%s sent a frame with nothing sealed in it", self._host)
                return
            body = self._sealed.open(message.data)
        else:
            if message.type is not aiohttp.WSMsgType.TEXT:
                _LOGGER.debug("%s sent a frame with nothing said in it", self._host)
                return
            body = message.data
        try:
            said = json.loads(body)
        except ValueError:
            _LOGGER.debug("%s said something that is not JSON", self._host)
            return
        if isinstance(said, dict):
            await self._handle(said)

    async def _handle(self, said: dict[str, Any]) -> None:
        resource = str(said.get("resource") or "")
        action = str(said.get("action") or "")
        if "code" in said:
            _LOGGER.debug("%s refused %s with %s", self._host, resource, said["code"])
            return
        if action == POST and resource == INITIAL:
            await self._begin(said)
            return
        if action in (RESPONSE, NOTIFY) and resource in (VALUES, EVERYTHING):
            self._values(said.get("data"))

    async def _begin(self, said: dict[str, Any]) -> None:
        """Take up the conversation the appliance has just opened.

        It hands over the session and the number our first message must carry,
        and expects to be told what it is talking to before it will say
        anything else.
        """
        self._sid = said.get("sID")
        data = said.get("data")
        first = data[0] if isinstance(data, list) and data else {}
        self._msgid = int(first.get("edMsgID", 1))
        await self._reply(
            said,
            {
                "deviceType": "Application",
                "deviceName": "Home Assistant",
                "deviceID": self._identifier,
            },
        )
        # What it can do, then everything it is currently holding. The
        # descriptions are asked for because an appliance will not send values
        # for anything it has not described to us first.
        await self._ask(SERVICES)
        await self._ask(
            AUTHENTICATION,
            version=2,
            data={"nonce": secrets.token_urlsafe(32).rstrip("=")},
        )
        await self._ask(READY, version=2, action=NOTIFY)
        await self._ask(DESCRIPTIONS)
        await self._ask(EVERYTHING)
        self._on_connected(True)

    def _values(self, data: Any) -> None:
        """What the appliance says it is holding, by the number of each."""
        if not isinstance(data, list):
            return
        held = {
            int(one["uid"]): one.get("value")
            for one in data
            if isinstance(one, dict) and isinstance(one.get("uid"), int)
        }
        if held:
            self._on_values(held)

    async def _reply(self, said: dict[str, Any], data: Any) -> None:
        await self._write(
            {
                "sID": said.get("sID"),
                "msgID": said.get("msgID"),
                "resource": said.get("resource"),
                "version": said.get("version", 1),
                "action": RESPONSE,
                "data": [data],
            }
        )

    async def _ask(
        self,
        resource: str,
        version: int = 1,
        action: str = GET,
        data: Any = None,
    ) -> None:
        message: dict[str, Any] = {
            "sID": self._sid,
            "msgID": self._msgid,
            "resource": resource,
            "version": version,
            "action": action,
        }
        if data is not None:
            message["data"] = [data]
        self._msgid += 1
        await self._write(message)

    async def _write(self, message: dict[str, Any]) -> None:
        socket = self._socket
        if socket is None or socket.closed:
            raise HomeConnectConnectionError(f"{self._host} is not listening")
        body = json.dumps(message, separators=(",", ":"))
        if self._sealed is not None:
            await socket.send_bytes(self._sealed.seal(body))
        else:
            await socket.send_str(body)

    async def write(self, uid: int, value: Any) -> None:
        """Set one thing on the appliance, by the number it goes by."""
        await self._ask(VALUES, action=POST, data={"uid": uid, "value": value})

    async def refresh(self) -> None:
        """Ask again for everything it is holding."""
        await self._ask(EVERYTHING)
