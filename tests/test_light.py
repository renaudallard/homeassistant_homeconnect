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

"""Lamps, which an appliance keeps as two or three separate settings."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import API, set_up

HAID = "SIEMENS-HB678GBS6B-FEDCBA987654"
AT = f"{API}/homeappliances/{HAID}"


@pytest.fixture
async def oven(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AiohttpClientMocker:
    await set_up(hass, aioclient_mock, "oven")
    aioclient_mock.clear_requests()
    return aioclient_mock


async def test_the_settings_of_a_lamp_become_one_light(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    state = hass.states.get("light.oven_light")
    assert state is not None
    assert state.state == "on"
    # Seventy percent of the ten to a hundred the oven said it takes.
    assert state.attributes["brightness"] == 171
    assert state.attributes["color_mode"] == "brightness"


async def test_the_settings_a_lamp_is_made_of_are_not_also_controls(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    """One lamp is one thing, not a switch and a number beside it."""
    assert hass.states.get("switch.oven_lighting") is None
    assert hass.states.get("number.oven_lighting_brightness") is None
    assert hass.states.get("switch.oven_ambient_light_enabled") is None
    assert hass.states.get("select.oven_ambient_light_colour") is None


async def test_a_lamp_with_a_colour_offers_one(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    state = hass.states.get("light.oven_ambient_light")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["supported_color_modes"] == ["rgb"]
    # A lamp that is off reports no colour, so ask the entity rather than the
    # state: what is being checked is the reading of the appliance's hex.
    lamp = hass.data["entity_components"]["light"].get_entity(
        "light.oven_ambient_light"
    )
    assert lamp.rgb_color == (74, 136, 248)


async def test_switching_a_lamp_on_sends_only_that(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    oven.put(f"{AT}/settings/BSH.Common.Setting.AmbientLightEnabled", status=204)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.oven_ambient_light"}, blocking=True
    )
    assert len(oven.mock_calls) == 1
    _, url, body, _ = oven.mock_calls[0]
    assert str(url).endswith("/settings/BSH.Common.Setting.AmbientLightEnabled")
    assert body["data"]["value"] is True


async def test_setting_a_colour_says_it_is_a_colour_of_our_own_first(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    """The appliance keeps a palette and will not take a colour until it has
    been told to expect one."""
    oven.put(f"{AT}/settings/BSH.Common.Setting.AmbientLightColor", status=204)
    oven.put(f"{AT}/settings/BSH.Common.Setting.AmbientLightCustomColor", status=204)
    oven.put(f"{AT}/settings/BSH.Common.Setting.AmbientLightEnabled", status=204)
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.oven_ambient_light", "rgb_color": (255, 0, 128)},
        blocking=True,
    )
    written = [(str(url), body["data"]["value"]) for _, url, body, _ in oven.mock_calls]
    assert written[0][0].endswith("AmbientLightColor")
    assert written[0][1] == "BSH.Common.EnumType.AmbientLightColor.CustomColor"
    assert written[1][0].endswith("AmbientLightCustomColor")
    assert written[1][1] == "#ff0080"
    assert written[2][0].endswith("AmbientLightEnabled")


async def test_setting_the_brightness_sends_the_percentage_the_lamp_uses(
    hass: HomeAssistant, oven: AiohttpClientMocker
) -> None:
    oven.put(f"{AT}/settings/Cooking.Common.Setting.LightingBrightness", status=204)
    oven.put(f"{AT}/settings/Cooking.Common.Setting.Lighting", status=204)
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.oven_light", "brightness": 255},
        blocking=True,
    )
    written = {str(url): body["data"]["value"] for _, url, body, _ in oven.mock_calls}
    brightness = next(v for k, v in written.items() if k.endswith("LightingBrightness"))
    assert brightness == 100


async def test_an_appliance_with_no_lamp_gets_no_light(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await set_up(hass, aioclient_mock, "washer")
    assert not [one for one in hass.states.async_entity_ids("light")]
