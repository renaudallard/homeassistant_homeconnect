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

"""What a reading is measured in."""

from __future__ import annotations

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime

from custom_components.homeconnect.measures import measure_for


@pytest.mark.parametrize(
    ("unit", "expected", "device_class"),
    [
        ("°C", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
        ("°F", UnitOfTemperature.FAHRENHEIT, SensorDeviceClass.TEMPERATURE),
        ("seconds", UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
        ("%", PERCENTAGE, None),
    ],
)
def test_the_unit_says_what_kind_of_quantity_it_is(
    unit: str, expected: str, device_class: SensorDeviceClass | None
) -> None:
    found = measure_for("K", unit)
    assert found is not None
    assert found.unit == expected
    assert found.device_class == device_class


def test_a_unit_nobody_here_knows_is_left_alone() -> None:
    """Better no unit than one Home Assistant would convert wrongly."""
    assert measure_for("K", "furlongs") is None
    assert measure_for("K", None) is None


def test_a_battery_is_told_from_a_programme_halfway_through() -> None:
    """Both are percentages and only one of them means the appliance is dying."""
    battery = measure_for("BSH.Common.Status.BatteryLevel", "%")
    progress = measure_for("BSH.Common.Option.ProgramProgress", "%")
    assert battery is not None and battery.device_class is SensorDeviceClass.BATTERY
    assert progress is not None and progress.device_class is None
