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

"""Things about an appliance that are either so or not so.

Anything the appliance reports as true or false becomes one of these, along
with the door, which it reports as a word but which is a door, and whatever it
is currently complaining about.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import names
from .capability import STATUS, happening, leaf
from .coordinator import DOOR_STATE, HomeConnectCoordinator
from .entity import HomeConnectEntity, KeyEntity, follow, statuses

# What the door says when it is open. Locked is a kind of shut, and a machine
# mid-cycle spends the whole wash saying it.
OPEN = "Open"


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _connections, _connection)
    follow(entry, coordinator, add, _doors, _door)
    follow(entry, coordinator, add, _flags, _flag)
    follow(entry, coordinator, add, _events, _event)


def _connections(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    for haid in coordinator.data:
        yield haid, "connection"


def _doors(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    for haid, appliance in coordinator.data.items():
        if DOOR_STATE in appliance.status:
            yield haid, DOOR_STATE


def _flags(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return statuses(coordinator, wanted_boolean=True)


def _events(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    for haid, appliance in coordinator.data.items():
        for key in appliance.events:
            yield haid, key


class ConnectionSensor(HomeConnectEntity, BinarySensorEntity):
    """Whether the appliance can be reached at all.

    The one entity that means something while the appliance is unreachable,
    so it is the one that does not go unavailable along with it.
    """

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid)
        self._attr_unique_id = f"{haid}-connection"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.appliance is not None

    @property
    def is_on(self) -> bool:
        appliance = self.appliance
        return appliance is not None and appliance.connected


class DoorSensor(KeyEntity, BinarySensorEntity):
    """Whether the door is open."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator, haid, DOOR_STATE, STATUS)

    @property
    def is_on(self) -> bool | None:
        value = self.held
        return None if not isinstance(value, str) else leaf(value) == OPEN

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Shut and locked are both shut, and the difference is worth keeping.

        A washing machine spends the whole of a cycle with the door locked,
        which is not the same as merely closed, and nothing about open or
        shut can say so.
        """
        value = self.held
        if not isinstance(value, str):
            return None
        return {"value": value, "shown": self.shown}


class FlagSensor(KeyEntity, BinarySensorEntity):
    """Something the appliance reports as true or false."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str
    ) -> None:
        super().__init__(coordinator, haid, key, STATUS)

    @property
    def is_on(self) -> bool | None:
        value = self.held
        return None if value is None else bool(value)


class EventSensor(HomeConnectEntity, BinarySensorEntity):
    """Something the appliance is complaining about, or has just finished.

    These are not settings or readings and are described nowhere: an event is
    either happening or it is not, and the appliance only mentions one at all
    once it has something to say about it.
    """

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str
    ) -> None:
        super().__init__(coordinator, haid)
        self._key = key
        self._attr_unique_id = f"{haid}-{key}"
        self._attr_name = names.readable(key)

    @property
    def is_on(self) -> bool | None:
        appliance = self.appliance
        found = appliance.events.get(self._key) if appliance is not None else None
        if found is None or found.value is None:
            return None
        return happening(found.value)


def _connection(
    coordinator: HomeConnectCoordinator, haid: str, _key: str
) -> ConnectionSensor:
    return ConnectionSensor(coordinator, haid)


def _door(coordinator: HomeConnectCoordinator, haid: str, _key: str) -> DoorSensor:
    return DoorSensor(coordinator, haid)


def _flag(coordinator: HomeConnectCoordinator, haid: str, key: str) -> FlagSensor:
    return FlagSensor(coordinator, haid, key)


def _event(coordinator: HomeConnectCoordinator, haid: str, key: str) -> EventSensor:
    return EventSensor(coordinator, haid, key)
