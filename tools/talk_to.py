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


"""Hold a conversation with one appliance from the command line.

    python tools/talk_to.py --host 172.20.0.209 --key-file tmp/hob.key
    python tools/talk_to.py --host 172.20.0.209 --key-file tmp/hob.key \
        --describe tmp/hob --minutes 90

Runs the integration's own link against a real appliance, outside Home
Assistant, and prints what comes back: every frame, every batch of values and
every change of connection, with the time beside each. Given the directory
holding the appliance's two description files, values are printed by the key
each stands for rather than by number.

It only listens. Nothing here writes to the appliance, on purpose: it is a
real machine, and a wrong write is a wrong write on a cooktop.

The key is read from a file rather than the command line so that it lands in
neither the shell history nor the process list. It is the shared secret the
appliance answers to, and anyone holding it on the same network can drive the
appliance, so keep the file under tmp/, which is not tracked.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, ".")

from custom_components.homeconnect import iddf, local
from custom_components.homeconnect.hcp import HcpLink

# Anything whose key says it names one particular machine is not printed.
NAMING = ("serial", "mac", "identifier", "id")


def _secret(path: Path) -> str:
    found = path.read_text().strip()
    if not found:
        raise SystemExit(f"{path} is empty")
    return found


def _described(where: Path | None) -> dict[int, iddf.Entry] | None:
    if where is None:
        return None
    mapping = next(where.glob("*FeatureMapping.xml"), None)
    description = next(where.glob("*DeviceDescription.xml"), None)
    if mapping is None or description is None:
        raise SystemExit(f"{where} does not hold the two description files")
    return iddf.parse(mapping.read_bytes(), description.read_bytes())


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def _names_one(key: str) -> bool:
    return any(word in key.rsplit(".", 1)[-1].lower() for word in NAMING)


class Listening:
    """What has been heard so far, and when."""

    def __init__(self, entries: dict[int, iddf.Entry] | None) -> None:
        self.entries = entries
        self.batches = 0
        self.seen: set[int] = set()
        self.connected_at: float | None = None
        self.connected_for = 0.0

    def values(self, held: dict[int, Any]) -> None:
        self.batches += 1
        self.seen.update(held)
        print(f"{_stamp()} {len(held)} values", flush=True)
        if self.entries is None:
            for uid, value in sorted(held.items()):
                print(f"    {uid:#06x} = {value!r}")
            return
        sorted_out = local.sort(self.entries, held)
        for kind, readings in (
            ("status", sorted_out.status),
            ("setting", sorted_out.settings),
            ("option", sorted_out.options),
            ("event", sorted_out.events),
        ):
            for key, reading in sorted(readings.items()):
                shown = "<hidden>" if _names_one(key) else repr(reading.value)
                unit = f" {reading.unit}" if reading.unit else ""
                print(f"    {kind:8s} {key} = {shown}{unit}")
        if sorted_out.active is not None:
            print(f"    active   {sorted_out.active}")
        if sorted_out.selected is not None:
            print(f"    selected {sorted_out.selected}")
        unknown = [uid for uid in held if uid not in self.entries]
        if unknown:
            print(f"    {len(unknown)} not described: {[hex(u) for u in unknown]}")

    def connection(self, talking: bool) -> None:
        now = time.monotonic()
        if talking:
            self.connected_at = now
            print(f"{_stamp()} connected", flush=True)
        else:
            if self.connected_at is not None:
                self.connected_for += now - self.connected_at
                self.connected_at = None
            print(f"{_stamp()} disconnected", flush=True)

    def summary(self) -> str:
        if self.connected_at is not None:
            self.connected_for += time.monotonic() - self.connected_at
            self.connected_at = None
        return (
            f"{self.batches} batches, {len(self.seen)} distinct things, "
            f"connected for {self.connected_for:.0f}s in total"
        )


async def _talk(args: argparse.Namespace) -> None:
    listening = Listening(_described(args.describe))
    key = _secret(args.key_file)
    iv = _secret(args.iv_file) if args.iv_file else None
    async with aiohttp.ClientSession() as session:
        link = HcpLink(
            session,
            args.host,
            key,
            iv,
            listening.values,
            listening.connection,
            port=args.port,
        )
        print(f"{_stamp()} opening {link.url} for {args.minutes} minutes", flush=True)
        link.start(asyncio.get_running_loop().create_task)
        try:
            await asyncio.sleep(args.minutes * 60)
        except asyncio.CancelledError:
            pass
        finally:
            await link.stop()
    print(f"{_stamp()} {listening.summary()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", required=True, help="address the appliance is at")
    parser.add_argument(
        "--key-file", type=Path, required=True, help="file holding the shared key"
    )
    parser.add_argument(
        "--iv-file",
        type=Path,
        help="file holding the starting vector, for an appliance that seals "
        "its messages rather than its connection",
    )
    parser.add_argument("--port", type=int, help="port, where not the usual one")
    parser.add_argument(
        "--describe",
        type=Path,
        help="directory holding the appliance's two description files",
    )
    parser.add_argument(
        "--minutes", type=float, default=2.0, help="how long to listen for"
    )
    parser.add_argument("--quiet", action="store_true", help="frames are not shown")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.quiet else logging.DEBUG,
        format="%(asctime)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Only the link's own log is wanted; aiohttp and asyncio have plenty to say.
    for noisy in ("aiohttp", "asyncio", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        asyncio.run(_talk(args))
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
