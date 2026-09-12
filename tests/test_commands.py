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

"""Telling an appliance to do something, and what goes over the wire."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import API, set_up, state_of

HAID = "BOSCH-WAV28MH0GB-1234567890AB"
AT = f"{API}/homeappliances/{HAID}"


@pytest.fixture
async def washer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AiohttpClientMocker:
    await set_up(hass, aioclient_mock, "washer")
    aioclient_mock.clear_requests()
    return aioclient_mock


def sent(mock: AiohttpClientMocker) -> tuple[str, str, dict[str, Any]]:
    """The one call that was made, as its method, its address and its body."""
    method, url, data, _ = mock.mock_calls[-1]
    return method, str(url), data


async def test_a_name_goes_back_as_the_words_it_is(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """A favourite is given a name, not a figure between two ends."""
    washer.put(f"{AT}/settings/BSH.Common.Setting.Favorite.001.Name", status=204)
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": "text.washer_favourite_1_name", "value": "Sunday wash"},
        blocking=True,
    )
    method, url, body = sent(washer)
    assert method == "PUT"
    assert url.endswith("/settings/BSH.Common.Setting.Favorite.001.Name")
    assert body == {
        "data": {"key": "BSH.Common.Setting.Favorite.001.Name", "value": "Sunday wash"}
    }
    assert state_of(hass, "text.washer_favourite_1_name") == "Sunday wash"


async def test_a_switch_sends_true_and_false(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    washer.put(f"{AT}/settings/BSH.Common.Setting.ChildLock", status=204)
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.washer_child_lock"},
        blocking=True,
    )
    method, url, body = sent(washer)
    assert method == "PUT"
    assert url.endswith("/settings/BSH.Common.Setting.ChildLock")
    assert body == {"data": {"key": "BSH.Common.Setting.ChildLock", "value": True}}
    assert state_of(hass, "switch.washer_child_lock") == "on"


async def test_a_switch_over_a_choice_sends_the_appliance_its_own_word(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """The power setting has no true and false, only on and off."""
    washer.put(f"{AT}/settings/BSH.Common.Setting.PowerState", status=204)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.washer_power_state"}, blocking=True
    )
    _, _, body = sent(washer)
    assert body["data"]["value"] == "BSH.Common.EnumType.PowerState.Off"


async def test_a_number_sends_a_whole_figure_as_a_whole_one(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    washer.put(f"{AT}/settings/LaundryCare.Washer.Setting.IDos1BaseLevel", status=204)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.washer_i_dos_1_base_level", "value": 300},
        blocking=True,
    )
    _, _, body = sent(washer)
    assert body["data"]["value"] == 300
    assert not isinstance(body["data"]["value"], float)


async def test_an_option_goes_to_the_programme_that_is_set(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """Nothing is running, so it is the selected programme that is adjusted."""
    key = "LaundryCare.Washer.Option.SpinSpeed"
    washer.put(f"{AT}/programs/selected/options/{key}", status=204)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.washer_spin_speed", "option": "800 rpm"},
        blocking=True,
    )
    _, url, body = sent(washer)
    assert url.endswith(f"/programs/selected/options/{key}")
    assert body["data"]["value"] == "LaundryCare.Washer.EnumType.SpinSpeed.RPM800"
    assert state_of(hass, "select.washer_spin_speed") == "800 rpm"


async def test_an_option_that_only_goes_in_at_the_start_is_held_back(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """The cloud takes a delayed start, answers as though it worked, and
    ignores it. So it is kept here until there is a start to send it with."""
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.washer_start_in_relative", "time": "01:00:00"},
        blocking=True,
    )
    assert washer.mock_calls == []
    assert state_of(hass, "time.washer_start_in_relative") == "01:00:00"


async def test_starting_carries_what_was_held_back(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.washer_start_in_relative", "time": "01:00:00"},
        blocking=True,
    )
    washer.put(f"{AT}/programs/active", status=204)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.washer_start_programme"}, blocking=True
    )
    method, url, body = sent(washer)
    assert method == "PUT"
    assert url.endswith("/programs/active")
    assert body["data"]["key"] == "LaundryCare.Washer.Program.Cotton"
    assert body["data"]["options"] == [
        {"key": "BSH.Common.Option.StartInRelative", "value": 3600}
    ]


async def test_choosing_a_programme_puts_it_in_the_selected_slot(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    washer.put(f"{AT}/programs/selected", status=204)
    washer.get(
        f"{AT}/programs/available/LaundryCare.Washer.Program.EasyCare",
        json={"data": {"key": "LaundryCare.Washer.Program.EasyCare", "options": []}},
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.washer_programme", "option": "Easy care"},
        blocking=True,
    )
    method, url, body = (
        washer.mock_calls[0][0],
        str(washer.mock_calls[0][1]),
        washer.mock_calls[0][2],
    )
    assert method == "PUT"
    assert url.endswith("/programs/selected")
    assert body["data"]["key"] == "LaundryCare.Washer.Program.EasyCare"


async def test_a_command_is_a_flag_that_only_goes_true(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    key = "BSH.Common.Command.PauseProgram"
    washer.put(f"{AT}/commands/{key}", status=204)
    # It is only offered while something is running, so ask the entity
    # directly rather than working the appliance up to that state.
    await (
        hass.data["entity_components"]["button"]
        .get_entity("button.washer_pause_programme")
        .async_press()
    )
    _, url, body = sent(washer)
    assert url.endswith(f"/commands/{key}")
    assert body == {"data": {"key": key, "value": True}}


async def test_a_refusal_is_passed_on_word_for_word(
    hass: HomeAssistant, washer: AiohttpClientMocker
) -> None:
    """The reason is the only thing that says what to go and do about it."""
    washer.put(
        f"{AT}/settings/BSH.Common.Setting.ChildLock",
        status=409,
        json={
            "error": {
                "key": "SDK.Error.WrongOperationState",
                "description": "The door is open",
            }
        },
    )
    with pytest.raises(HomeAssistantError, match="The door is open"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.washer_child_lock"},
            blocking=True,
        )
