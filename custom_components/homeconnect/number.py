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

"""Figures an appliance will take between two ends.

Anything settable that the appliance described with a smallest and a largest
value becomes one of these. The ends and the step come from the appliance, so
an oven that goes to 300 degrees and one that goes to 250 each offer what they
have without anything here knowing which is which.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability import NUMBER, OPTION, SETTING
from .coordinator import HomeConnectCoordinator
from .entity import SettableEntity, follow, options, settings
from .measures import measure_for


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _settings, _setting_number)
    follow(entry, coordinator, add, _options, _option_number)


def _settings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return settings(coordinator, NUMBER)


def _options(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return options(coordinator, NUMBER)


class HomeConnectNumber(SettableEntity, NumberEntity):
    """One figure of one appliance, within the range it named."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str, kind: str
    ) -> None:
        super().__init__(coordinator, haid, key, kind)
        described = self.described
        measure = measure_for(key, described.unit if described else None)
        if measure is not None:
            self._attr_native_unit_of_measurement = measure.unit
            # A number takes a narrower set of these than a reading does, and
            # one it does not know is worse than none: it would be drawn as
            # something it is not.
            self._attr_device_class = _known(measure.device_class)

    @property
    def native_min_value(self) -> float:
        """The lowest it will take under the programme now in force.

        A programme narrows what its options will take: a wool wash will not
        go to ninety degrees whatever the machine is capable of. So the ends
        are read afresh rather than fixed when the entity was made.
        """
        bounds = self._bounds
        return bounds[0] if bounds is not None else 0.0

    @property
    def native_max_value(self) -> float:
        bounds = self._bounds
        return bounds[1] if bounds is not None else 0.0

    @property
    def native_step(self) -> float:
        """How far apart the figures it will take are.

        A step of nothing is a step of one: an appliance that counts in whole
        degrees and does not bother to say so is not offering tenths of one.
        """
        described = self.described
        return described.step if described is not None and described.step else 1.0

    @property
    def _bounds(self) -> tuple[float, float] | None:
        """The two ends, where the appliance named both of them."""
        described = self.described
        if described is None or described.minimum is None or described.maximum is None:
            return None
        return described.minimum, described.maximum

    @property
    def native_value(self) -> float | None:
        value = self.held
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Send a figure back in the shape the appliance sends it in.

        Home Assistant hands every number over as a fraction, and an appliance
        that counts its degrees and its seconds in whole ones reports them
        whole. Sending 60.0 where it said 60 is the same figure written a way
        it never writes it.
        """
        await self.apply(int(value) if float(value).is_integer() else value)


def _known(device_class: Any) -> NumberDeviceClass | None:
    """The same kind of quantity, if a number has a name for it."""
    if device_class is None:
        return None
    try:
        return NumberDeviceClass(str(device_class))
    except ValueError:
        return None


def _setting_number(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectNumber:
    return HomeConnectNumber(coordinator, haid, key, SETTING)


def _option_number(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectNumber:
    return HomeConnectNumber(coordinator, haid, key, OPTION)
