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

"""Things an appliance can be told to do once.

Starting and stopping a programme are two of them and are always there.
The rest are whatever the appliance says it will take, which is a short list
of pausing, resuming and opening the door, and differs by machine.

An appliance will not be worked from anywhere but its own front panel until
remote control has been armed on the panel itself, and starting needs a second
permission on top of that. Nothing here can grant either, so a button that
would only earn a refusal is not offered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import names
from .capability import leaf
from .coordinator import OPERATION_STATE, HomeConnectCoordinator
from .entity import HomeConnectEntity, follow
from .errors import HomeConnectError

# Two of the commands only make sense at one point in a cycle. Pressing
# resume on a machine that is not paused is a refusal waiting to happen, and
# the appliance says plainly enough which point it is at.
WHEN = {
    "BSH.Common.Command.PauseProgram": frozenset({"Run"}),
    "BSH.Common.Command.ResumeProgram": frozenset({"Pause"}),
}

START = "start"
STOP = "stop"


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _running, _run_button)
    follow(entry, coordinator, add, _commands, _command_button)


def _running(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    """A start and a stop for every appliance that runs programmes."""
    for haid, appliance in coordinator.data.items():
        if appliance.programs or appliance.program is not None:
            yield haid, START
            yield haid, STOP


def _commands(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    for haid, appliance in coordinator.data.items():
        for key in appliance.model.commands:
            yield haid, key


class HomeConnectButton(HomeConnectEntity, ButtonEntity):
    """Something the appliance will do when asked."""

    @property
    def available(self) -> bool:
        appliance = self.appliance
        return super().available and appliance is not None and appliance.remote_control

    async def _asking(self, doing: Any) -> None:
        """Ask, and pass on what the appliance said if it would not."""
        try:
            await doing
        except HomeConnectError as err:
            raise HomeAssistantError(str(err)) from err


class StartButton(HomeConnectButton):
    """Start whatever the appliance is set to run."""

    _attr_name = "Start"

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-start"

    @property
    def available(self) -> bool:
        appliance = self.appliance
        if not super().available or appliance is None:
            return False
        # Nothing to start if nothing is set, nothing to start if it is
        # already going, and nothing to start until the appliance has been
        # told at its own panel that it may be started from elsewhere.
        return (
            appliance.selected is not None
            and not appliance.running
            and appliance.remote_start
        )

    async def async_press(self) -> None:
        await self._asking(self.coordinator.start_program(self._haid))


class StopButton(HomeConnectButton):
    """Stop whatever the appliance is doing."""

    _attr_name = "Stop"

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-stop"

    @property
    def available(self) -> bool:
        appliance = self.appliance
        return super().available and appliance is not None and appliance.running

    async def async_press(self) -> None:
        await self._asking(self.coordinator.stop_program(self._haid))


class CommandButton(HomeConnectButton):
    """One of the things the appliance says it will be told to do."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str
    ) -> None:
        super().__init__(coordinator, haid)
        self._key = key
        self._attr_unique_id = f"{haid}-{key}"
        self._attr_name = names.readable(key)

    @property
    def available(self) -> bool:
        appliance = self.appliance
        if not super().available or appliance is None:
            return False
        wanted = WHEN.get(self._key)
        if wanted is None:
            return True
        state = appliance.status.get(OPERATION_STATE)
        return state is not None and leaf(str(state.value)) in wanted

    async def async_press(self) -> None:
        await self._asking(self.coordinator.send_command(self._haid, self._key))


def _run_button(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectButton:
    return (
        StartButton(coordinator, haid)
        if key == START
        else StopButton(coordinator, haid)
    )


def _command_button(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> CommandButton:
    return CommandButton(coordinator, haid, key)
