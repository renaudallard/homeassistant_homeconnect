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

"""Choices an appliance offers.

Anything with a named set of values it will take becomes one of these, and so
does the programme itself: what an appliance will run is a list it hands over,
and it is a different list when the door is open or a cycle is under way.

The words in the list are the appliance's own, translated by the cloud into
whatever Home Assistant is set to. Where it offered none, the value's own key
says plainly enough what it is.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import names
from .capability import OPTION, SELECT, SETTING
from .coordinator import HomeConnectCoordinator
from .entity import HomeConnectEntity, SettableEntity, follow, options, settings
from .errors import HomeConnectError


def choices(values: tuple[str, ...], shown: Mapping[str, str] | None) -> dict[str, str]:
    """What to show for each value the appliance will take, by what to show.

    Two values that come out reading the same are told apart by where they
    sit, since a list offering the same word twice is a list where one of them
    cannot be chosen.
    """
    labelled = {
        value: (shown or {}).get(value) or names.label(value) for value in values
    }
    settled = names.distinct(list(values), labelled)
    return {settled[value]: value for value in values}


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _settings, _setting_select)
    follow(entry, coordinator, add, _options, _option_select)
    follow(entry, coordinator, add, _programs, _program_select)


def _settings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return settings(coordinator, SELECT)


def _options(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return options(coordinator, SELECT)


def _programs(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    for haid, appliance in coordinator.data.items():
        if appliance.programs or appliance.program is not None:
            yield haid, "program"


class HomeConnectSelect(SettableEntity, SelectEntity):
    """One thing with a fixed set of values that can be set."""

    @property
    def _choices(self) -> dict[str, str]:
        described = self.described
        if described is None:
            return {}
        return choices(described.values, described.shown)

    @property
    def options(self) -> list[str]:
        return list(self._choices)

    @property
    def current_option(self) -> str | None:
        """Whatever it is set to, named the way the list names it.

        A value the appliance has settled on that was never on the list is
        still what it is set to, and saying nothing would be worse than saying
        something that cannot be chosen again.
        """
        value = self.held
        if not isinstance(value, str):
            return None
        for shown, named in self._choices.items():
            if named == value:
                return shown
        return self.shown

    async def async_select_option(self, option: str) -> None:
        await self.apply(self._choices.get(option, option))


class ProgramSelect(HomeConnectEntity, SelectEntity):
    """Which programme the appliance will run next.

    Setting one does not start it. Which programmes are on offer moves with
    what the appliance is doing, and only what it is offering now is listed,
    since anything else earns a refusal.
    """

    _attr_translation_key = "program"

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-program"

    @property
    def _choices(self) -> dict[str, str]:
        appliance = self.appliance
        if appliance is None:
            return {}
        offered = list(appliance.programs)
        # What it is set to stays on the list even once it stops being
        # offered, which is what happens the moment a cycle starts.
        for held in (appliance.selected, appliance.active):
            if held is not None and held not in offered:
                offered.append(held)
        return choices(tuple(offered), appliance.program_names)

    @property
    def available(self) -> bool:
        appliance = self.appliance
        if not super().available or appliance is None:
            return False
        # An appliance that is off, or whose door is open, offers nothing.
        # Neither does one that has not been told to accept instructions.
        return bool(self._choices) and appliance.remote_control

    @property
    def options(self) -> list[str]:
        return list(self._choices)

    @property
    def current_option(self) -> str | None:
        appliance = self.appliance
        if appliance is None or appliance.program is None:
            return None
        for shown, key in self._choices.items():
            if key == appliance.program:
                return shown
        return None

    async def async_select_option(self, option: str) -> None:
        program = self._choices.get(option)
        if program is None:
            raise HomeAssistantError(f"{option} is not on offer")
        try:
            await self.coordinator.select_program(self._haid, program)
        except HomeConnectError as err:
            raise HomeAssistantError(str(err)) from err


def _setting_select(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSelect:
    return HomeConnectSelect(coordinator, haid, key, SETTING)


def _option_select(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectSelect:
    return HomeConnectSelect(coordinator, haid, key, OPTION)


def _program_select(
    coordinator: HomeConnectCoordinator, haid: str, _key: str
) -> ProgramSelect:
    return ProgramSelect(coordinator, haid)
