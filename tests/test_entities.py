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

"""What an appliance turns into, end to end.

Everything the cloud answers comes out of the fixture, so what these check is
the reading of it rather than the writing of the fixture.
"""

from __future__ import annotations

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import set_up, state_of

WASHER = "sensor.washer_operation_state"


@pytest.fixture
async def washer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AiohttpClientMocker:
    await set_up(hass, aioclient_mock, "washer")
    return aioclient_mock


async def test_the_appliance_becomes_a_device(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    registry = dr.async_get(hass)
    device = registry.async_get_device(
        {("homeconnect", "BOSCH-WAV28MH0GB-1234567890AB")}
    )
    assert device is not None
    assert device.name == "Washer"
    assert device.manufacturer == "Bosch"
    assert device.model == "WAV28MH0GB"
    assert device.model_id == "WAV28MH0GB/01"
    assert device.serial_number == "1234567890AB"


async def test_a_status_becomes_a_reading(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get(WASHER)
    assert state is not None
    # What the cloud calls it, with the appliance's own word for it beside.
    assert state.state == "Ready"
    assert state.attributes["value"] == "BSH.Common.EnumType.OperationState.Ready"


async def test_a_status_holding_a_flag_becomes_a_binary_sensor(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    assert state_of(hass, "binary_sensor.washer_remote_control_active") == "on"
    assert state_of(hass, "binary_sensor.washer_local_control_active") == "off"


async def test_the_door_is_a_door(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("binary_sensor.washer_door_state")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["device_class"] == "door"


async def test_being_reachable_is_its_own_reading(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("binary_sensor.washer_connection")
    assert state is not None
    assert state.state == "on"


async def test_a_settable_flag_becomes_a_switch(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("switch.washer_child_lock")
    assert state is not None
    assert state.state == "off"


async def test_a_choice_between_on_and_off_becomes_a_switch(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """The power setting offers two values and one of them is on."""
    state = hass.states.get("switch.washer_power_state")
    assert state is not None
    assert state.state == "on"


async def test_a_bounded_figure_becomes_a_number(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("number.washer_i_dos_1_base_level")
    assert state is not None
    assert state.state == "200.0"
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 500
    assert state.attributes["step"] == 10


async def test_the_programme_is_a_choice_of_what_is_on_offer(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("select.washer_programme")
    assert state is not None
    assert state.state == "Cottons"
    assert sorted(state.attributes["options"]) == ["Cottons", "Easy care"]


async def test_an_option_of_the_programme_becomes_a_choice(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """The words are the appliance's own, which is where 40 °C comes from."""
    state = hass.states.get("select.washer_spin_speed")
    assert state is not None
    assert state.state == "1200 rpm"
    assert sorted(state.attributes["options"]) == ["1200 rpm", "800 rpm"]


async def test_an_option_counted_in_seconds_is_a_length_of_time(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("sensor.washer_remaining_programme_time")
    assert state is not None
    assert state.state == "7200"
    assert state.attributes["device_class"] == "duration"
    assert state.attributes["unit_of_measurement"] == "s"


async def test_the_commands_the_appliance_offers_become_buttons(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    assert hass.states.get("button.washer_pause_programme") is not None
    assert hass.states.get("button.washer_resume_programme") is not None


async def test_starting_is_offered_and_stopping_is_not(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """A programme is selected and nothing is running, so one of the two."""
    start = hass.states.get("button.washer_start")
    stop = hass.states.get("button.washer_stop")
    assert start is not None and start.state != "unavailable"
    assert stop is not None and stop.state == "unavailable"


async def test_pausing_is_not_offered_while_nothing_is_running(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    assert state_of(hass, "button.washer_pause_programme") == "unavailable"


async def test_an_event_becomes_something_that_is_happening_or_not(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    state = hass.states.get("binary_sensor.washer_i_dos_1_fill_level_poor")
    assert state is not None
    assert state.state == "off"


async def test_what_says_how_it_is_reached_is_kept_out_of_the_way(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    registry = er.async_get(hass)
    remote = registry.async_get("binary_sensor.washer_remote_control_active")
    assert remote is not None
    assert remote.entity_category is EntityCategory.DIAGNOSTIC


async def test_a_measured_setting_is_a_control_and_an_unmeasured_one_is_not(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """A dose in millilitres is a control; a volume with no unit is a setting."""
    registry = er.async_get(hass)
    dose = registry.async_get("number.washer_i_dos_1_base_level")
    volume = registry.async_get("number.washer_sound_volume")
    assert dose is not None and dose.entity_category is None
    assert volume is not None and volume.entity_category is EntityCategory.CONFIG


async def test_switching_an_appliance_on_is_never_filed_as_configuration(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    registry = er.async_get(hass)
    power = registry.async_get("switch.washer_power_state")
    assert power is not None
    assert power.entity_category is None
