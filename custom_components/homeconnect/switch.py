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

"""Things that can be turned on and off.

A setting the appliance holds as true or false is one of these, and so is a
choice between exactly two values where one of them is on: a power setting
offering nothing but on and standby is a switch however it writes the two.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability import OPTION, SETTING, SWITCH
from .coordinator import HomeConnectCoordinator
from .entity import SettableEntity, follow, options, settings


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _settings, _setting_switch)
    follow(entry, coordinator, add, _options, _option_switch)


def _settings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return settings(coordinator, SWITCH)


def _options(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return options(coordinator, SWITCH)


class HomeConnectSwitch(SettableEntity, SwitchEntity):
    """One thing that is either on or off."""

    @property
    def is_on(self) -> bool | None:
        value = self.held
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        described = self.described
        return described is not None and value == described.on_value()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.apply(self._either(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.apply(self._either(False))

    def _either(self, on: bool) -> Any:
        """What this appliance calls on and off, in its own words.

        Most say true and false. The ones that offer a choice of two instead
        want one of the two back, and which two is theirs to decide.
        """
        described = self.described
        if described is None or described.boolean:
            return on
        named = described.on_value() if on else described.off_value()
        return named if named is not None else on


def _setting_switch(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSwitch:
    return HomeConnectSwitch(coordinator, haid, key, SETTING)


def _option_switch(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSwitch:
    return HomeConnectSwitch(coordinator, haid, key, OPTION)
