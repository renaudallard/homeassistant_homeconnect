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

"""What the cloud pushes, and what it changes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.coordinator import SETTLE, HomeConnectCoordinator
from custom_components.homeconnect.events import Event

from .common import set_up, state_of

HAID = "BOSCH-WAV28MH0GB-1234567890AB"


def item(key: str, value: object, **extra: object) -> dict[str, object]:
    return {"key": key, "value": value, **extra}


@pytest.fixture
async def washer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> HomeConnectCoordinator:
    entry = await set_up(hass, aioclient_mock, "washer")
    coordinator: HomeConnectCoordinator = entry.runtime_data.coordinator
    return coordinator


async def test_a_status_change_reaches_the_entity(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(
        Event(
            "STATUS",
            HAID,
            {
                "items": [
                    item(
                        "BSH.Common.Status.OperationState",
                        "BSH.Common.EnumType.OperationState.Run",
                        displayvalue="Running",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    assert state_of(hass, "sensor.washer_operation_state") == "Running"


async def test_a_setting_change_reaches_the_switch(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(
        Event("NOTIFY", HAID, {"items": [item("BSH.Common.Setting.ChildLock", True)]})
    )
    await hass.async_block_till_done()
    assert state_of(hass, "switch.washer_child_lock") == "on"


async def test_an_option_change_reaches_the_choice(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(
        Event(
            "NOTIFY",
            HAID,
            {
                "items": [
                    item(
                        "LaundryCare.Washer.Option.SpinSpeed",
                        "LaundryCare.Washer.EnumType.SpinSpeed.RPM800",
                        displayvalue="800 rpm",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    assert state_of(hass, "select.washer_spin_speed") == "800 rpm"


async def test_something_starting_becomes_the_active_programme(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(
        Event(
            "NOTIFY",
            HAID,
            {
                "items": [
                    item(
                        "BSH.Common.Root.ActiveProgram",
                        "LaundryCare.Washer.Program.Cotton",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    assert washer.data[HAID].active == "LaundryCare.Washer.Program.Cotton"
    assert state_of(hass, "sensor.washer_active_programme") == "Cottons"


async def test_an_event_reaches_the_thing_that_is_happening(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(
        Event(
            "EVENT",
            HAID,
            {
                "items": [
                    item(
                        "LaundryCare.Washer.Event.IDos1FillLevelPoor",
                        "BSH.Common.EnumType.EventPresentState.Present",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor.washer_i_dos_1_fill_level_poor") == "on"


async def test_an_event_nobody_has_heard_of_becomes_an_entity(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    """An appliance only mentions an event once it has something to say."""
    washer.apply(
        Event(
            "EVENT",
            HAID,
            {
                "items": [
                    item(
                        "LaundryCare.Common.Event.DryingProcessFinished",
                        "BSH.Common.EnumType.EventPresentState.Present",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.washer_drying_process_finished")
    assert state is not None
    assert state.state == "on"


async def test_an_appliance_going_away_takes_its_entities_with_it(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(Event("DISCONNECTED", HAID, {}))
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor.washer_connection") == "off"
    assert state_of(hass, "switch.washer_child_lock") == "unavailable"


async def test_the_connection_reading_survives_the_appliance_going_away(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    """It is the one entity that means something while nothing answers."""
    washer.apply(Event("DISCONNECTED", HAID, {}))
    await hass.async_block_till_done()
    assert state_of(hass, "binary_sensor.washer_connection") == "off"


async def test_an_event_about_an_appliance_nobody_knows_is_let_alone(
    hass: HomeAssistant, washer: HomeConnectCoordinator
) -> None:
    washer.apply(Event("STATUS", "SIEMENS-XX-99", {"items": [item("A.B.Status.C", 1)]}))
    await hass.async_block_till_done()
    assert "SIEMENS-XX-99" not in washer.data


async def test_an_appliance_coming_back_is_read_again_in_full(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    washer: HomeConnectCoordinator,
) -> None:
    """It has been away, and what it says now is not what it said when it went."""
    washer.apply(Event("DISCONNECTED", HAID, {}))
    await hass.async_block_till_done()
    so_far = len(aioclient_mock.mock_calls)

    washer.apply(Event("CONNECTED", HAID, {}))
    await hass.async_block_till_done()
    # Nothing is asked until the events stop arriving.
    assert len(aioclient_mock.mock_calls) == so_far

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=SETTLE + 1))
    await hass.async_block_till_done()
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls[so_far:]]
    assert any(one.endswith("/status") for one in asked)
    assert any(one.endswith("/settings") for one in asked)
    assert any(one.endswith("/programs/available") for one in asked)


async def test_a_programme_change_asks_only_what_moved_with_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    washer: HomeConnectCoordinator,
) -> None:
    """What an appliance offers moves with the programme; what it reports about
    itself does not, and the stream carries that anyway."""
    so_far = len(aioclient_mock.mock_calls)
    washer.apply(
        Event(
            "NOTIFY",
            HAID,
            {
                "items": [
                    item(
                        "BSH.Common.Root.SelectedProgram",
                        "LaundryCare.Washer.Program.EasyCare",
                    )
                ]
            },
        )
    )
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=SETTLE + 1))
    await hass.async_block_till_done()
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls[so_far:]]
    assert any(one.endswith("/programs/available") for one in asked)
    assert not any(one.endswith("/status") for one in asked)
