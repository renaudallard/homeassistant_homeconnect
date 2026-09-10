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

"""What a reading is measured in, and what kind of thing it is.

An appliance names the unit of anything it counts, and that name is enough to
say both what Home Assistant should call the unit and what sort of quantity it
is. Nothing here looks at the key, so a reading from an appliance nobody has
seen is measured the same way as one from the appliance this was written
against.

Two readings are the exception. A percentage says nothing about what is being
measured, and a battery has to be told apart from a programme that is halfway
through, so those two are picked out by name.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)


@dataclass(frozen=True)
class Measure:
    """How one reading is written down."""

    unit: str
    device_class: SensorDeviceClass | None = None


# By the unit the appliance names, lowercased. The cloud is not consistent
# about how it spells a unit between appliances, so every spelling seen in the
# documentation is here rather than only the one a given oven happens to use.
MEASURES: dict[str, Measure] = {
    "°c": Measure(UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "°f": Measure(UnitOfTemperature.FAHRENHEIT, SensorDeviceClass.TEMPERATURE),
    "c": Measure(UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "f": Measure(UnitOfTemperature.FAHRENHEIT, SensorDeviceClass.TEMPERATURE),
    "seconds": Measure(UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
    "s": Measure(UnitOfTime.SECONDS, SensorDeviceClass.DURATION),
    "minutes": Measure(UnitOfTime.MINUTES, SensorDeviceClass.DURATION),
    "gram": Measure(UnitOfMass.GRAMS, SensorDeviceClass.WEIGHT),
    "g": Measure(UnitOfMass.GRAMS, SensorDeviceClass.WEIGHT),
    "kg": Measure(UnitOfMass.KILOGRAMS, SensorDeviceClass.WEIGHT),
    "ml": Measure(UnitOfVolume.MILLILITERS, SensorDeviceClass.VOLUME),
    "l": Measure(UnitOfVolume.LITERS, SensorDeviceClass.VOLUME),
    "litre": Measure(UnitOfVolume.LITERS, SensorDeviceClass.VOLUME),
    "liter": Measure(UnitOfVolume.LITERS, SensorDeviceClass.VOLUME),
    "kwh": Measure(UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "wh": Measure(UnitOfEnergy.WATT_HOUR, SensorDeviceClass.ENERGY),
    "rpm": Measure(REVOLUTIONS_PER_MINUTE),
    "dbm": Measure(
        SIGNAL_STRENGTH_DECIBELS_MILLIWATT, SensorDeviceClass.SIGNAL_STRENGTH
    ),
    "%": Measure(PERCENTAGE),
}

# Readings counted in percent that are about how full something is rather than
# how far through it is. Home Assistant draws a battery for these and knows
# what a low one means, which it cannot work out from the unit alone.
BATTERIES = frozenset(
    {
        "BSH.Common.Status.BatteryLevel",
        "ConsumerProducts.CleaningRobot.Status.BatteryLevel",
    }
)


def measure_for(key: str, unit: str | None) -> Measure | None:
    """How to write down one reading, or nothing if it is not a quantity."""
    if unit is None:
        return None
    found = MEASURES.get(unit.strip().lower())
    if found is None:
        return None
    if found.unit == PERCENTAGE and key in BATTERIES:
        return Measure(PERCENTAGE, SensorDeviceClass.BATTERY)
    return found
