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

"""The manifest, and the rules hassfest holds it to.

None of these run outside CI, so the ones that have caught us out are kept
here where they cost a second rather than a round trip.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.homeconnect.const import DOMAIN

MANIFEST = json.loads(
    (
        Path(__file__).parent.parent / "custom_components" / DOMAIN / "manifest.json"
    ).read_text()
)


def test_the_keys_are_in_the_order_hassfest_wants() -> None:
    """Domain and name first, then alphabetical, and it is strict about it."""
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_it_says_what_it_needs_to_say() -> None:
    assert MANIFEST["domain"] == DOMAIN
    assert MANIFEST["config_flow"] is True
    # A custom integration is refused without one, and HACS releases off it.
    assert MANIFEST["version"]
    # Nothing is installed to run this. Home Assistant already ships aiohttp.
    assert MANIFEST["requirements"] == []


def test_the_service_an_appliance_announces_is_the_one_we_listen_for() -> None:
    assert MANIFEST["zeroconf"] == ["_homeconnect._tcp.local."]
