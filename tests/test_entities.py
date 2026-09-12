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
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import device_for, set_up, state_of

WASHER = "sensor.washer_operation_state"


@pytest.fixture
async def washer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    return await set_up(hass, aioclient_mock, "washer")


async def test_cloud_mode_without_the_stream_asks_often(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """Reached through the cloud, the poll is what carries the changes until
    the stream is up, so it is the fast one."""
    from custom_components.homeconnect.coordinator import SCAN_INTERVAL

    assert washer.runtime_data.coordinator.update_interval == SCAN_INTERVAL


async def test_the_appliance_becomes_a_device(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    device = device_for(hass, washer, "BOSCH-WAV28MH0GB-1234567890AB")
    assert device is not None
    assert device.name == "Washer"
    assert device.manufacturer == "Bosch"
    assert device.model == "WAV28MH0GB"
    assert device.model_id == "WAV28MH0GB/01"
    # Taken from the listing, which gives it outright, rather than read out
    # of the identifier, which not every appliance writes it into.
    assert device.serial_number == "1234567890AB"


async def test_a_status_becomes_a_reading(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get(WASHER)
    assert state is not None
    # What the cloud calls it, with the appliance's own word for it beside.
    assert state.state == "Ready"
    assert state.attributes["value"] == "BSH.Common.EnumType.OperationState.Ready"


async def test_a_tally_is_a_figure_that_keeps_a_statistic(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("sensor.washer_programme_all_count_started")
    assert state is not None
    # A count carries no unit, but it is still a number and one that only
    # climbs, so it is kept as a figure with a running statistic rather than
    # written out as a word.
    assert state.state == "42"
    assert state.attributes["state_class"] == "total_increasing"


async def test_a_programme_machine_gets_a_programme_event(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """The thing to trigger on is there before the first programme ends."""
    state = hass.states.get("event.washer_programme")
    assert state is not None
    assert set(state.attributes["event_types"]) == {"finished", "aborted"}


async def test_an_appliance_that_runs_nothing_gets_no_programme_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await set_up(hass, aioclient_mock, "oven")
    assert hass.states.get("event.oven_programme") is None


async def test_a_status_holding_a_flag_becomes_a_binary_sensor(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    assert state_of(hass, "binary_sensor.washer_remote_control_active") == "on"
    assert state_of(hass, "binary_sensor.washer_local_control_active") == "off"


async def test_the_door_is_a_door(hass: HomeAssistant, washer: MockConfigEntry) -> None:
    state = hass.states.get("binary_sensor.washer_door_state")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["device_class"] == "door"


async def test_being_reachable_is_its_own_reading(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("binary_sensor.washer_connection")
    assert state is not None
    assert state.state == "on"


async def test_a_settable_flag_becomes_a_switch(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("switch.washer_child_lock")
    assert state is not None
    assert state.state == "off"


async def test_a_choice_between_on_and_off_becomes_a_switch(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """The power setting offers two values and one of them is on."""
    state = hass.states.get("switch.washer_power_state")
    assert state is not None
    assert state.state == "on"


async def test_a_bounded_figure_becomes_a_number(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("number.washer_i_dos_1_base_level")
    assert state is not None
    assert state.state == "200.0"
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 500
    assert state.attributes["step"] == 10


async def test_the_programme_is_a_choice_of_what_is_on_offer(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("select.washer_programme")
    assert state is not None
    assert state.state == "Cottons"
    assert sorted(state.attributes["options"]) == ["Cottons", "Easy care"]


async def test_an_option_of_the_programme_becomes_a_choice(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """The words are the appliance's own, which is where 40 °C comes from."""
    state = hass.states.get("select.washer_spin_speed")
    assert state is not None
    assert state.state == "1200 rpm"
    assert sorted(state.attributes["options"]) == ["1200 rpm", "800 rpm"]


async def test_an_option_counted_in_seconds_is_a_length_of_time(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("sensor.washer_remaining_programme_time")
    assert state is not None
    assert state.state == "7200"
    assert state.attributes["device_class"] == "duration"
    assert state.attributes["unit_of_measurement"] == "s"


async def test_the_commands_the_appliance_offers_become_buttons(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    assert hass.states.get("button.washer_pause_programme") is not None
    assert hass.states.get("button.washer_resume_programme") is not None


async def test_a_dangerous_command_is_built_but_left_switched_off(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """A factory reset is a press nobody should trip over, so the button is
    there for whoever wants it but not switched on out of the box."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    found = registry.async_get("button.washer_apply_factory_reset")
    assert found is not None
    assert found.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # So it has no state to press.
    assert hass.states.get("button.washer_apply_factory_reset") is None
    # An ordinary command is still there and usable.
    assert hass.states.get("button.washer_pause_programme") is not None


async def test_starting_is_offered_and_stopping_is_not(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """A programme is selected and nothing is running, so one of the two."""
    start = hass.states.get("button.washer_start_programme")
    stop = hass.states.get("button.washer_stop_programme")
    assert start is not None and start.state != "unavailable"
    assert stop is not None and stop.state == "unavailable"


async def test_pausing_is_not_offered_while_nothing_is_running(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    assert state_of(hass, "button.washer_pause_programme") == "unavailable"


async def test_an_event_becomes_something_that_is_happening_or_not(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    state = hass.states.get("binary_sensor.washer_i_dos_1_fill_level_poor")
    assert state is not None
    assert state.state == "off"


async def test_a_reading_that_is_a_list_says_how_many_rather_than_what(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """Written out, a list of error codes is unreadable, and a long one is
    past the longest state Home Assistant will hold, which loses the entity
    at the moment it finally has something to say."""
    state = hass.states.get("sensor.washer_error_codes_list")
    assert state is not None
    assert state.state == "2"
    assert state.attributes["value"] == {"length": 2, "list": ["E:01", "E:02"]}


async def test_something_holding_words_becomes_a_text_box(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """A favourite is given a name, and a name is not a figure between two
    ends. What the appliance says about one is how long it may be."""
    state = hass.states.get("text.washer_favourite_1_name")
    assert state is not None
    assert state.state == "Quick wash"
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 30
    # And it is not also offered as a figure.
    assert hass.states.get("number.washer_favourite_1_name") is None


async def test_which_way_the_appliance_is_reached_is_a_reading(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """Which way it would be reached, told apart from whether it is
    answering, which is the connection beside it."""
    state = hass.states.get("sensor.washer_transport")
    assert state is not None
    assert state.state == "cloud"
    registry = er.async_get(hass)
    found = registry.async_get("sensor.washer_transport")
    assert found is not None
    assert found.entity_category is EntityCategory.DIAGNOSTIC


async def test_what_says_how_it_is_reached_is_kept_out_of_the_way(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    remote = registry.async_get("binary_sensor.washer_remote_control_active")
    assert remote is not None
    assert remote.entity_category is EntityCategory.DIAGNOSTIC


async def test_a_measured_setting_is_a_control_and_an_unmeasured_one_is_not(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    """A dose in millilitres is a control; a volume with no unit is a setting."""
    registry = er.async_get(hass)
    dose = registry.async_get("number.washer_i_dos_1_base_level")
    volume = registry.async_get("number.washer_sound_volume")
    assert dose is not None and dose.entity_category is None
    assert volume is not None and volume.entity_category is EntityCategory.CONFIG


async def test_switching_an_appliance_on_is_never_filed_as_configuration(
    hass: HomeAssistant, washer: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    power = registry.async_get("switch.washer_power_state")
    assert power is not None
    assert power.entity_category is None
