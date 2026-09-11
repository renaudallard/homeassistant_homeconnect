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

"""One account's worth of cloud, served out of a fixture.

Every test that sets the integration up wants the same handful of endpoints
answering the same way, so they are registered once here. What each answers
comes from the fixture rather than from the code under test, which is what
makes a test that passes mean something.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.const import (
    API_HOST,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

API = f"{API_HOST}/api"


def fixture(name: str) -> dict[str, Any]:
    """One of the appliances the tests are written against."""
    path = Path(__file__).parent / "fixtures" / f"{name}.json"
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def device_for(
    hass: HomeAssistant, made: MockConfigEntry, haid: str
) -> dr.DeviceEntry | None:
    """The device one appliance was given, if it still has one.

    An identifier is only unique within a config entry, so the entry is part
    of the question rather than something to be worked out from the answer.
    """
    registry = dr.async_get(hass)
    return registry.async_get_device_by_identifier((DOMAIN, haid), made.entry_id)


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    """What one entity is showing, insisting that it is there at all."""
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} was never made"
    return found.state


def shown_by(hass: HomeAssistant, entity_id: str) -> Mapping[str, Any]:
    """What one entity says about itself beyond its state."""
    found = hass.states.get(entity_id)
    assert found is not None, f"{entity_id} was never made"
    return found.attributes


def wrapped(named: str, members: Any) -> dict[str, Any]:
    """An answer in the envelope the cloud puts everything in."""
    return {"data": {named: members}}


def described_as(haid: str) -> bytes:
    """A description archive shaped the way the cloud sends one."""
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as bundle:
        bundle.writestr(
            f"{haid}_FeatureMapping.xml",
            (FIXTURES / "FeatureMapping.xml").read_bytes(),
        )
        bundle.writestr(
            f"{haid}_DeviceDescription.xml",
            (FIXTURES / "DeviceDescription.xml").read_bytes(),
        )
    return made.getvalue()


def serve(mock: AiohttpClientMocker, appliances: list[dict[str, Any]]) -> None:
    """Answer everything the integration asks about these appliances."""
    # An event stream that says nothing and ends. A test that is about the
    # stream serves its own; this is here so that one that is not does not
    # trip over a connection nobody registered.
    mock.get(f"{API}/homeappliances/events", text="")
    mock.get(
        f"{API}/homeappliances",
        json=wrapped("homeappliances", [one["appliance"] for one in appliances]),
    )
    for one in appliances:
        haid = one["appliance"]["haId"]
        # The description, which only the report asks for, and which it asks
        # for on the account service rather than the appliance API.
        for host in ("eu", "na"):
            mock.get(
                f"https://{host}.services.home-connect.com/api/iddf/v1/iddf/{haid}",
                content=described_as(haid),
            )
        at = f"{API}/homeappliances/{haid}"
        mock.get(f"{at}/status", json=wrapped("status", one["status"]))
        mock.get(f"{at}/settings", json=wrapped("settings", one["settings"]))
        for key, described in one["setting_details"].items():
            mock.get(f"{at}/settings/{key}", json={"data": described})
        mock.get(f"{at}/commands", json=wrapped("commands", one["commands"]))
        mock.get(f"{at}/events", json={"items": one["events"]})
        mock.get(f"{at}/programs/available", json=wrapped("programs", one["available"]))
        for key, described in one["program_options"].items():
            mock.get(f"{at}/programs/available/{key}", json={"data": described})
        active = one.get("active")
        mock.get(
            f"{at}/programs/active",
            status=200 if active else 404,
            json={"data": active} if active else {},
        )
        selected = one.get("selected")
        mock.get(
            f"{at}/programs/selected",
            status=200 if selected else 404,
            json={"data": selected} if selected else {},
        )


def entry(hass: HomeAssistant, email: str | None = None) -> MockConfigEntry:
    """An account already signed in, with a token that has not expired."""
    data: dict[str, Any] = {
        CONF_ACCESS_TOKEN: "an-access-token",
        CONF_REFRESH_TOKEN: "a-refresh-token",
        CONF_EXPIRES_AT: time.time() + 3600,
    }
    if email is not None:
        data[CONF_EMAIL] = email
    made = MockConfigEntry(
        domain=DOMAIN,
        title="Home Connect",
        unique_id="account-under-test",
        data=data,
    )
    made.add_to_hass(hass)
    return made


async def set_up(
    hass: HomeAssistant, mock: AiohttpClientMocker, *named: str
) -> MockConfigEntry:
    """Set the integration up against these appliances and wait for it.

    The event stream is left unopened. What it carries is folded in by hand
    where that is what a test is about, which keeps every other test from
    depending on a connection that reopens itself on a timer.
    """
    serve(mock, [fixture(name) for name in named])
    made = entry(hass)
    with patch("custom_components.homeconnect.HomeConnectStream.start"):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()
    return made
