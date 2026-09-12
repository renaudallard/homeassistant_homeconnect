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

"""Delayed start, set on a clock.

The option that puts a programme off is a length of time the appliance counts
in seconds and holds until the programme starts. A slider of seconds is a
clumsy way to say "in two and a half hours", so it is offered as a clock
instead, the hours and minutes of the delay. A clock goes no further than a
second short of a full day, which is as long a delay as these appliances take;
a delay given as exactly a day is held at that last second.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability import DELAYED, NUMBER, OPTION
from .const import DOMAIN
from .coordinator import HomeConnectCoordinator
from .entity import SettableEntity, delayed_options, follow

# The most a clock holds: a second short of a full day. No appliance seen asks
# for a longer delay, and one given as a full day is held at this.
LONGEST = 24 * 3600 - 1


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    _drop_stale_numbers(hass, coordinator)
    follow(entry, coordinator, add, delayed_options, _delayed_time)


def _drop_stale_numbers(
    hass: HomeAssistant, coordinator: HomeConnectCoordinator
) -> None:
    """Take out the number a delayed-start option used to be.

    It was a number before it was a clock. An appliance set up under the older
    release keeps that number in the registry, where it would sit unavailable
    for good beside the clock, so it is removed rather than left behind.
    """
    registry = er.async_get(hass)
    for haid in coordinator.data:
        for key in DELAYED:
            stale = registry.async_get_entity_id(NUMBER, DOMAIN, f"{haid}-{key}")
            if stale is not None:
                registry.async_remove(stale)


class HomeConnectTime(SettableEntity, TimeEntity):
    """A delay before a programme starts, set on a clock rather than in seconds."""

    @property
    def native_value(self) -> time | None:
        value = self.held
        if not isinstance(value, (int, float)):
            return None
        seconds = max(0, min(int(value), LONGEST))
        return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)

    async def async_set_value(self, value: time) -> None:
        """Send the delay back as the seconds the appliance counts it in."""
        await self.apply(value.hour * 3600 + value.minute * 60 + value.second)


def _delayed_time(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectTime:
    return HomeConnectTime(coordinator, haid, key, OPTION)
