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

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .common import set_up

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
    ]


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
    device = dr.async_get(hass).async_get_device({("homeconnect", HAID)})
    assert device is not None
    report = await async_get_device_diagnostics(hass, entry, device)
    assert len(report["appliances"]) == 1
