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

"""Readings from an appliance.

Anything the appliance reports and nothing can be done about becomes one of
these, along with anything settable that it described too vaguely to offer as
a control. What a reading is measured in comes from the appliance, so a figure
it counts in seconds is a length of time here without anything having to know
which figure it was.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import names
from .capability import OPTION, SENSOR, SETTING, STATUS
from .coordinator import HomeConnectCoordinator
from .entity import HomeConnectEntity, KeyEntity, follow, options, settings, statuses
from .measures import Measure, measure_for

# Where an appliance says how long is left of what it is doing. It is an
# option of the programme rather than a status, because it is about the
# programme rather than about the machine.
REMAINING = "BSH.Common.Option.RemainingProgramTime"

# A remaining time that has moved by less than this is the same estimate
# arriving again, and recomputing the finishing time from it would walk the
# clock about for the whole of a wash.
DRIFT = timedelta(seconds=45)


def _counts(key: str) -> bool:
    """Whether a reading is a lifetime tally rather than a measurement.

    An appliance keeps count of the programmes it has run and the hours it
    has spent running them. Those only ever go up, which is what lets Home
    Assistant work out how many were run this month.
    """
    return ".Count." in key or key.endswith(("Count", "Counter"))


def _state_class(key: str, measure: Measure) -> SensorStateClass:
    if measure.device_class is SensorDeviceClass.ENERGY or _counts(key):
        return SensorStateClass.TOTAL_INCREASING
    return SensorStateClass.MEASUREMENT


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _statuses, _status_sensor)
    follow(entry, coordinator, add, _settings, _setting_sensor)
    follow(entry, coordinator, add, _options, _option_sensor)
    follow(entry, coordinator, add, _programs, _program_sensor)
    follow(entry, coordinator, add, _endings, _finish_sensor)


def _statuses(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return statuses(coordinator, wanted_boolean=False)


def _settings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return settings(coordinator, SENSOR)


def _options(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return options(coordinator, SENSOR)


def _programs(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    """One reading per appliance saying what it is running.

    Every appliance that has ever offered a programme gets one, and it says
    nothing while none is running, which is a truthful answer rather than an
    absent entity.
    """
    for haid, appliance in coordinator.data.items():
        if appliance.programs or appliance.program is not None:
            yield haid, "active"


def _endings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    """One clock per appliance that says how long it has left."""
    for haid, appliance in coordinator.data.items():
        described = any(
            REMAINING in options_of for options_of in appliance.model.options.values()
        )
        if described or REMAINING in appliance.options:
            yield haid, "finish"


class HomeConnectSensor(KeyEntity, SensorEntity):
    """One reading of one appliance."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str, kind: str
    ) -> None:
        super().__init__(coordinator, haid, key, kind)
        self._measure = measure_for(key, self._unit_of())
        if self._measure is not None:
            self._attr_native_unit_of_measurement = self._measure.unit
            self._attr_device_class = self._measure.device_class
            self._attr_state_class = _state_class(key, self._measure)

    def _unit_of(self) -> str | None:
        """What this reading is measured in, from wherever it was said.

        A setting says so where it is described and again every time it is
        reported. An appliance that is off has not reported anything yet, so
        the description is what there is to go on.
        """
        described = self.described
        if described is not None and described.unit:
            return described.unit
        found = self.reading
        return found.unit if found is not None else None

    @property
    def native_value(self) -> Any:
        """The reading, as a figure where it is one and as words otherwise."""
        if self._measure is None:
            return self.shown
        value = self.held
        return value if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The appliance's own name for what it is holding.

        The reading itself is written the way the cloud writes it for whoever
        is reading, which follows the language Home Assistant is set to. An
        automation wants the name that does not, so it is here.

        A reading that is a list of things shows how many there are, so what
        they are goes here, there being nowhere else for them.
        """
        value = self.held
        if isinstance(value, str) and "." in value:
            return {"value": value}
        if isinstance(value, (Mapping, list)):
            return {"value": value}
        return None


class ProgramSensor(HomeConnectEntity, SensorEntity):
    """What the appliance is running, if anything."""

    _attr_name = "Active programme"

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-active-program"

    @property
    def native_value(self) -> str | None:
        appliance = self.appliance
        if appliance is None or appliance.active is None:
            return None
        return appliance.program_names.get(appliance.active) or names.label(
            appliance.active
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        appliance = self.appliance
        if appliance is None or appliance.active is None:
            return None
        return {"value": appliance.active}


class FinishSensor(HomeConnectEntity, SensorEntity):
    """When what the appliance is doing is expected to be over."""

    _attr_name = "Finish at"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-finish-at"
        self._at: datetime | None = None

    @property
    def native_value(self) -> datetime | None:
        """The moment it should be done, held still while the estimate is.

        An appliance counts down in whole minutes and repeats itself in
        between, so working the finishing time out afresh every time it says
        anything would move it about by a minute in each direction for the
        whole of a cycle. It is only moved when the appliance has changed its
        mind by more than the counting down explains.
        """
        appliance = self.appliance
        left = appliance.options.get(REMAINING) if appliance is not None else None
        if appliance is None or not appliance.running or left is None:
            self._at = None
            return None
        seconds = left.value
        if not isinstance(seconds, (int, float)):
            return self._at
        ending = dt_util.utcnow().replace(microsecond=0) + timedelta(seconds=seconds)
        if self._at is None or abs(ending - self._at) > DRIFT:
            self._at = ending
        return self._at


def _status_sensor(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSensor:
    return HomeConnectSensor(coordinator, haid, key, STATUS)


def _setting_sensor(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSensor:
    return HomeConnectSensor(coordinator, haid, key, SETTING)


def _option_sensor(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSensor:
    return HomeConnectSensor(coordinator, haid, key, OPTION)


def _program_sensor(
    coordinator: HomeConnectCoordinator, haid: str, _key: str
) -> ProgramSensor:
    return ProgramSensor(coordinator, haid)


def _finish_sensor(
    coordinator: HomeConnectCoordinator, haid: str, _key: str
) -> FinishSensor:
    return FinishSensor(coordinator, haid)
