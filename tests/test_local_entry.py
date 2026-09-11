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

"""An account set up to reach its appliances directly.

The account still says which appliances exist and what they are called. Where
their state comes from and where a change is sent is what changes, and the
point of these is that nothing above the coordinator can tell which it was.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import iddf, local
from custom_components.homeconnect.const import CONF_TRANSPORT, LOCAL
from custom_components.homeconnect.errors import HomeConnectAuthError, HomeConnectError

from .common import entry, fixture, serve, state_of

HAID = "BOSCH-WAV28MH0GB-1234567890AB"
FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = (FIXTURES / "FeatureMapping.xml").read_bytes()
DESCRIPTION = (FIXTURES / "DeviceDescription.xml").read_bytes()


class Stub:
    """A connection that answers, and remembers what was sent down it.

    It behaves the way a real one does about saying so: nothing is connected
    until the connection reports that it is, which is what the coordinator
    waits for.
    """

    def __init__(self) -> None:
        self.talking = False
        self.written: list[tuple[int, Any]] = []
        self.said_so: Any = None

    def start(self, spawn: Any) -> None:
        self.talking = True
        if self.said_so is not None:
            self.said_so(True)

    async def stop(self) -> None:
        pass

    async def write(self, uid: int, value: Any) -> None:
        self.written.append((uid, value))


def _standing_in(link: Stub) -> Any:
    """Put the stub where a real connection would go, wired the same way."""

    def make(control: Any, haid: str, known: Any, where: Any) -> Stub:
        link.said_so = lambda up: control._on_connected(haid, up)
        return link

    return make


@pytest.fixture
async def talking(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> tuple[MockConfigEntry, Stub]:
    """An entry set up locally, with one appliance answering.

    Everything it says on the way up is captured, since what goes into the
    log on a normal setup is itself worth a test.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.homeconnect")
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    link = Stub()
    with (
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.keys",
            AsyncMock(return_value={HAID: {"key": "a-key"}}),
        ),
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.description",
            AsyncMock(return_value=b"a zip"),
        ),
        patch.object(iddf, "unpack", lambda _archive: iddf.parse(MAPPING, DESCRIPTION)),
        patch.object(
            local, "unpack", lambda _archive: iddf.parse(MAPPING, DESCRIPTION)
        ),
        patch.object(local.Finder, "start", AsyncMock()),
        patch.object(local.Finder, "stop", AsyncMock()),
        patch.object(
            local.Finder, "where", lambda _self, _haid: local.Where("host", 80)
        ),
        patch.object(local.LocalControl, "_make", _standing_in(link)),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()
    return made, link


async def test_the_identity_is_this_install_with_a_few_of_its_own_bytes(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    """Two Home Assistants on one network must not say the same thing to one
    appliance, so the name carries a few bytes of this install's own id."""
    from homeassistant.helpers import instance_id

    made, _ = talking
    control = made.runtime_data.local
    assert control is not None
    expected = f"homeassistant-{(await instance_id.async_get(hass))[-4:]}"
    assert control._identity == expected
    assert control._identity != "homeassistant"


async def test_local_mode_asks_the_account_rarely(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    """The live state comes over the appliance's own connection, so the
    account is polled only to catch a pairing or a rename. Asking every
    minute would spend the quota that reaching an appliance directly is meant
    to save."""
    from custom_components.homeconnect.coordinator import SCAN_INTERVAL_STREAMING

    made, _ = talking
    assert made.runtime_data.coordinator.update_interval == SCAN_INTERVAL_STREAMING


async def test_the_transport_says_local_when_that_is_how_it_is_reached(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    state = hass.states.get("sensor.washer_transport")
    assert state is not None
    assert state.state == "local"


async def test_a_setting_that_cannot_be_written_is_a_reading(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    """A description marks some settings read only. One of those becomes a
    reading rather than a control, and a reading that claims to be
    configuration is one Home Assistant refuses to add at all.
    """
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import entity_registry as er

    made = hass.states.get("sensor.washer_temperature_unit")
    assert made is not None
    entry = er.async_get(hass).async_get("sensor.washer_temperature_unit")
    assert entry is not None
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    # The writable ones are still configuration, and still controls.
    written = er.async_get(hass).async_get("switch.washer_child_lock")
    assert written is not None
    assert written.entity_category is EntityCategory.CONFIG


async def test_an_appliance_that_is_not_shouting_is_still_reached(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Discovery only hears an appliance that happens to be shouting. One
    heard before and quiet now is reached where it was last heard, which is
    the difference between working after a restart and not."""
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    link = Stub()
    with (
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.keys",
            AsyncMock(return_value={HAID: {"key": "a-key"}}),
        ),
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.description",
            AsyncMock(return_value=b"a zip"),
        ),
        patch.object(iddf, "unpack", lambda _archive: iddf.parse(MAPPING, DESCRIPTION)),
        patch.object(
            local, "unpack", lambda _archive: iddf.parse(MAPPING, DESCRIPTION)
        ),
        patch.object(local.Finder, "start", AsyncMock()),
        patch.object(local.Finder, "stop", AsyncMock()),
        # Nothing is shouting, which is what discovery hears most of the time.
        patch.object(local.Finder, "where", lambda _self, _haid: None),
        patch.object(local.LocalControl, "_make", _standing_in(link)),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()
        control = made.runtime_data.local
        assert control is not None
        assert not control.talking(HAID)

        # Once it has been heard of, that address is what is used next time.
        control._known[HAID] = replace(
            control._known[HAID], where=local.Where("host", 80)
        )
        control._look_again()
        await hass.async_block_till_done()
        assert control.talking(HAID)


async def test_the_serial_stays_out_of_the_log(
    hass: HomeAssistant,
    talking: tuple[MockConfigEntry, Stub],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setting up locally names the appliance in the log more than once, and
    the part of the name that says whose it is must not go in."""
    # Setting the entry up is the fixture's work, so what it said is kept
    # under that phase rather than under the test's own. Only what this
    # integration wrote counts: the harness standing in for the store logs
    # everything it is handed, which the real one does not.
    said = "\n".join(
        record.getMessage()
        for record in caplog.get_records("setup")
        if record.name.startswith("custom_components.homeconnect")
    )
    assert "learnt" in said
    assert "talking to" in said
    assert "1234567890AB" not in said


async def test_the_entities_come_from_the_appliance_rather_than_the_cloud(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    made, _ = talking
    coordinator = made.runtime_data.coordinator
    assert coordinator.local is not None
    assert coordinator.data[HAID].connected
    # Nothing was read over the appliance API: the description is what says
    # what there is, and the appliance itself says what it is holding.
    assert "BSH.Common.Setting.ChildLock" in coordinator.data[HAID].model.settings
    assert hass.states.get("switch.washer_child_lock") is not None


async def test_what_the_appliance_pushes_reaches_the_entities(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    made, _ = talking
    coordinator = made.runtime_data.coordinator
    # 0x0101 is the operation state and 5 is the member meaning running.
    coordinator.apply_locally(HAID, {0x0101: 5, 0x0102: True})
    await hass.async_block_till_done()
    assert state_of(hass, "sensor.washer_operation_state") == "Run"
    assert state_of(hass, "switch.washer_child_lock") == "on"


async def test_setting_something_goes_down_the_appliance_connection(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    """By the number it goes by, since that is all an appliance understands."""
    _, link = talking
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.washer_child_lock"}, blocking=True
    )
    assert link.written == [(0x0102, True)]


async def test_a_choice_goes_back_as_the_number_of_the_value(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    made, link = talking
    made.runtime_data.coordinator.apply_locally(HAID, {0x0100: 1})
    await hass.async_block_till_done()
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.washer_power_state", "option": "On"},
        blocking=True,
    )
    assert link.written == [(0x0100, 2)]


async def test_the_appliance_going_quiet_is_the_appliance_going_quiet(
    hass: HomeAssistant, talking: tuple[MockConfigEntry, Stub]
) -> None:
    made, _ = talking
    coordinator = made.runtime_data.coordinator
    coordinator.set_talking(HAID, False)
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor.washer_connection") == "off"
    assert state_of(hass, "switch.washer_child_lock") == "unavailable"


async def test_nothing_is_asked_of_the_cloud_beyond_the_listing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    talking: tuple[MockConfigEntry, Stub],
) -> None:
    """The whole point of local control is that the account is asked once who
    the appliances are and then left alone."""
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert any(one.endswith("/homeappliances") for one in asked)
    assert not any("/status" in one or "/settings" in one for one in asked)


async def test_the_account_service_refusing_is_not_a_reason_to_sign_in_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The appliance API took the same token a moment earlier, so sending the
    user round the sign in again cannot help and only confuses."""
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    with patch(
        "custom_components.homeconnect.api.HomeConnectAccount.keys",
        AsyncMock(side_effect=HomeConnectAuthError("rejected the access token (403)")),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    assert made.state is ConfigEntryState.SETUP_RETRY
    assert not [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == "reauth"
    ]


async def test_one_unreadable_description_does_not_stop_the_rest(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An appliance whose description will not read is skipped, not fatal.
    Letting it stop the setup would take local control of every other machine
    on the account with it, and leave the entry retrying for good."""
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    with (
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.keys",
            AsyncMock(return_value={HAID: {"key": "a-key"}}),
        ),
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.description",
            AsyncMock(side_effect=HomeConnectError("this description will not read")),
        ),
        patch.object(local.Finder, "start", AsyncMock()),
        patch.object(local.Finder, "stop", AsyncMock()),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    # The entry comes up rather than retrying, with nothing learnt locally.
    assert made.state is ConfigEntryState.LOADED
    control = made.runtime_data.local
    assert control is not None
    assert not control.knows(HAID)


async def test_an_account_that_publishes_no_key_says_why(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Not every appliance has a key kept for it. Saying so is the difference
    between a bug and a thing that cannot be done."""
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    with patch(
        "custom_components.homeconnect.api.HomeConnectAccount.keys",
        AsyncMock(return_value={}),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    assert made.state is ConfigEntryState.SETUP_RETRY
    assert "no key" in str(made.reason)
    assert "cloud" in str(made.reason)
