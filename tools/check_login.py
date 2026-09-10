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

"""Check the sign in and the appliance API against a real account.

This is not part of the integration. It walks the whole sign in, says which
step fails, and logs every request and answer so a failure can be diagnosed
without guessing.

It asks for the address and password of the account and walks the sign in the
way the integration does, without a browser. The password is read from the
terminal, never echoed and never written down.

Pass --dump DIR to write what every appliance is, what it can do and what it
is doing into that directory, with the serial numbers taken out, which is what
the entity mapping is built against.

Nothing secret is printed. The log replaces tokens, codes and the address
itself with a note of how long they were, so the output can be pasted into a
bug report. Pass -q to log only failures.

    python tools/check_login.py
    python tools/check_login.py --dump tmp/appliances
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sys
import time
from getpass import getpass
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, ".")

from custom_components.homeconnect import auth, singlekey
from custom_components.homeconnect.api import ACTIVE, SELECTED, HomeConnectApi
from custom_components.homeconnect.const import REDIRECT_URI_APP
from custom_components.homeconnect.errors import HomeConnectError
from custom_components.homeconnect.http import redact


def _step(number: int, what: str) -> None:
    print(f"\n{number}. {what}", flush=True)


def _hide(haid: str) -> str:
    """An appliance id with the part that names one machine taken out."""
    parts = haid.split("-")
    if len(parts) > 2:
        parts[2] = "hidden"
    return "-".join(parts)


async def _describe(api: HomeConnectApi, haid: str) -> dict[str, Any]:
    """Everything one appliance will say about itself.

    Each of these is asked for on its own and reported on its own, because the
    point of this is to find the one that does not answer.
    """
    described: dict[str, Any] = {}
    for what, asking in (
        ("status", api.status(haid)),
        ("settings", api.settings(haid)),
        ("commands", api.commands(haid)),
        ("events", api.events(haid)),
        ("available", api.available_programs(haid)),
    ):
        try:
            described[what] = await asking
            print(f"   {what}: {len(described[what])}")
        except HomeConnectError as err:
            described[what] = {"failed": str(err)}
            print(f"   {what}: {err}")
    for slot in (ACTIVE, SELECTED):
        try:
            described[slot] = await api.program(haid, slot)
        except HomeConnectError as err:
            described[slot] = {"failed": str(err)}
    print(f"   active: {described.get(ACTIVE)}")
    print(f"   selected: {described.get(SELECTED)}")

    described["settings_detail"] = {}
    for listed in described.get("settings") or []:
        key = listed.get("key") if isinstance(listed, dict) else None
        if not isinstance(key, str):
            continue
        try:
            described["settings_detail"][key] = await api.setting(haid, key)
        except HomeConnectError as err:
            described["settings_detail"][key] = {"failed": str(err)}

    described["program_options"] = {}
    for program in described.get("available") or []:
        key = program.get("key") if isinstance(program, dict) else None
        if not isinstance(key, str):
            continue
        try:
            described["program_options"][key] = await api.program_options(haid, key)
        except HomeConnectError as err:
            described["program_options"][key] = {"failed": str(err)}
    return described


async def run(into: Path | None) -> int:
    verifier = auth.verifier()
    state = secrets.token_urlsafe(16)

    _step(1, "Signing in to SingleKey ID")
    email = input("   Email address: ").strip()
    password = getpass("   Password: ")

    async with aiohttp.ClientSession() as session:
        try:
            code = await singlekey.sign_in(session, email, password, verifier, state)
        except HomeConnectError as err:
            print(f"   failed: {err}")
            return 1
        print(f"   signed in, and handed back {len(code)} characters")

        _step(2, "Trading the code for a token pair")
        try:
            tokens = await auth.exchange(session, code, verifier, REDIRECT_URI_APP)
        except HomeConnectError as err:
            print(f"   failed: {err}")
            return 1
        left = tokens.expires_at - time.time()
        print(f"   got a pair, good for {left:.0f} seconds")

        api = HomeConnectApi(session, tokens, "en-GB")

        _step(3, "Reading the account")
        try:
            appliances = await api.appliances()
        except HomeConnectError as err:
            print(f"   failed: {err}")
            return 1
        for one in appliances:
            print(
                f"   {one.get('type')} {one.get('vib')} "
                f"{'connected' if one.get('connected') else 'offline'}"
            )

        _step(4, "Reading each appliance")
        dumped: dict[str, Any] = {}
        for one in appliances:
            haid = str(one.get("haId") or "")
            if not haid:
                continue
            print(f"\n   {one.get('name')} ({one.get('type')})")
            dumped[_hide(haid)] = {
                "appliance": {**one, "haId": _hide(haid)},
                **await _describe(api, haid),
            }

        if into is not None:
            into.mkdir(parents=True, exist_ok=True)
            for name, described in dumped.items():
                path = into / f"{name}.json"
                path.write_text(json.dumps(redact(described), indent=2))
                print(f"\n   wrote {path}")

    _step(5, "Everything answered")
    return 0


def main() -> int:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--dump", type=Path, help="write what each appliance said here")
    parsed.add_argument("-q", "--quiet", action="store_true", help="log only failures")
    args = parsed.parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.DEBUG,
        format="%(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(run(args.dump))


if __name__ == "__main__":
    raise SystemExit(main())
