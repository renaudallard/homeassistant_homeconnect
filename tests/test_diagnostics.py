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

"""What gets pasted into a bug report."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.homeconnect.errors import HomeConnectError

from .common import device_for, set_up

HAID = "BOSCH-WAV28MH0GB-1234567890AB"


async def test_the_account_report_carries_the_whole_of_what_was_said(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await set_up(hass, aioclient_mock, "washer")
    report = await async_get_config_entry_diagnostics(hass, entry)
    one = report["appliances"][0]
    assert one["type"] == "Washer"
    assert one["model"] == "WAV28MH0GB"
    assert "BSH.Common.Status.OperationState" in one["status"]
    assert "BSH.Common.Setting.PowerState" in one["describes"]["settings"][0]["key"]
    assert one["describes"]["commands"] == [
        "BSH.Common.Command.PauseProgram",
        "BSH.Common.Command.ResumeProgram",
        "BSH.Common.Command.ApplyFactoryReset",
    ]


async def test_the_report_carries_the_description_as_it_was_sent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """What was parsed is what this made of the description. What was sent is
    the description itself, and only that says whether something missing was
    never there or was dropped on the way in."""
    entry = await set_up(hass, aioclient_mock, "washer")
    report = await async_get_config_entry_diagnostics(hass, entry)
    described = report["appliances"][0]["description"]
    assert set(described) == {"FeatureMapping.xml", "DeviceDescription.xml"}
    assert "BSH.Common.Setting.PowerState" in described["FeatureMapping.xml"]
    assert "settingList" in described["DeviceDescription.xml"]


async def test_a_description_that_cannot_be_had_does_not_lose_the_report(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A report is worth having even when the cloud will not answer."""
    entry = await set_up(hass, aioclient_mock, "washer")
    with patch(
        "custom_components.homeconnect.api.HomeConnectAccount.description",
        AsyncMock(side_effect=HomeConnectError("nothing doing")),
    ):
        report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["appliances"][0]["description"] == {"error": "nothing doing"}
    assert report["appliances"][0]["status"]


async def test_no_report_says_whose_machine_it_is(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await set_up(hass, aioclient_mock, "washer")
    report = await async_get_config_entry_diagnostics(hass, entry)
    written = json.dumps(report)
    assert "1234567890AB" not in written
    assert "an-access-token" not in written
    assert "a-refresh-token" not in written
    # The model is not a secret and is the one thing a report needs.
    assert "WAV28MH0GB" in written


async def test_one_appliance_reports_only_itself(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await set_up(hass, aioclient_mock, "washer")
    device = device_for(hass, entry, HAID)
    assert device is not None
    report = await async_get_device_diagnostics(hass, entry, device)
    assert len(report["appliances"]) == 1
    # How often the account is asked is in the one report people send too.
    assert report["polling_seconds"] == 60.0
