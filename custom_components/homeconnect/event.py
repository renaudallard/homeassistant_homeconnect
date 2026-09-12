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

"""Programme events an appliance fires.

An appliance says when its programme has finished or been cut short, as a
one-off rather than as a thing that stays true. Left as a binary sensor that is
a flag flicking on and then off, which an automation has to catch on the turn;
as an event entity it fires the moment it happens, which is the shape Home
Assistant wants a trigger to have. The binary sensors are left where they are
for anyone already using them, and this sits beside them as the cleaner thing
to trigger on.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability import happening
from .coordinator import HomeConnectCoordinator
from .entity import HomeConnectEntity, follow

# The events worth firing, each by the key the appliance names it with and the
# word an automation triggers on. These are the one-off moments worth acting
# on: a programme ending, a cook reaching temperature, a timer going off. An
# appliance that does not have one of them simply never fires it. The lingering
# conditions, a door left open or salt running low, stay binary sensors, where
# a flag that holds is the right shape.
LIFECYCLE = {
    "BSH.Common.Event.ProgramFinished": "finished",
    "BSH.Common.Event.ProgramAborted": "aborted",
    "Cooking.Common.Event.PreheatFinished": "preheat_finished",
    "BSH.Common.Event.AlarmClockElapsed": "alarm_clock_elapsed",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _program_events, _program_event)


def _program_events(
    coordinator: HomeConnectCoordinator,
) -> Iterator[tuple[str, str]]:
    """One per appliance that runs programmes, before any has ended.

    Made from the appliance having programmes at all rather than from an event
    having turned up, so the thing to trigger on is there before the first
    finish rather than appearing only once one has happened.
    """
    for haid, appliance in coordinator.data.items():
        if appliance.programs or appliance.program is not None:
            yield haid, "program-event"


class ProgramEventEntity(HomeConnectEntity, EventEntity):
    """Fires at a one-off moment: a programme ending, a preheat or a timer."""

    _attr_name = "Programme"

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-program-event"
        self._attr_event_types = list(LIFECYCLE.values())
        # What each event was last seen doing, so only the turn into happening
        # fires. Seeded from now, not from nothing: an appliance already saying
        # a programme has finished when this starts up has not just finished,
        # and must wait to say so afresh before anything fires.
        self._on = {key: self._happening(key) for key in LIFECYCLE}

    def _happening(self, key: str) -> bool:
        appliance = self.appliance
        found = appliance.events.get(key) if appliance is not None else None
        return happening(found.value) if found is not None else False

    @callback
    def _handle_coordinator_update(self) -> None:
        for key, kind in LIFECYCLE.items():
            now = self._happening(key)
            if now and not self._on[key]:
                self._trigger_event(kind)
            self._on[key] = now
        super()._handle_coordinator_update()


def _program_event(
    coordinator: HomeConnectCoordinator, haid: str, _key: str
) -> ProgramEventEntity:
    return ProgramEventEntity(coordinator, haid)
