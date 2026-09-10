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

"""What every Home Connect entity has in common.

An entity stands for one key of one appliance. Which key it is comes from what
the appliance said about itself, so the platforms are thin: they say how a
value is presented and, where it can be set, how it is sent back.

An appliance gains and loses keys as it goes. A washing machine set to a wool
programme can be adjusted by things a cotton programme has never heard of, and
the cloud only describes the programme that is set. So entities are not all
made at setup: each platform is told to look again whenever the state moves,
and makes the ones that have appeared since.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import names
from .capability import GATHERED, OPTION, SETTING, Feature, Reading, platform_for
from .const import DOMAIN
from .coordinator import Appliance, HomeConnectCoordinator
from .errors import HomeConnectError

# Keys that say how the appliance is being reached rather than what it is
# doing. They belong on the page of an appliance that is misbehaving and
# nowhere else, which is what Home Assistant means by a diagnostic.
DIAGNOSTIC = frozenset(
    {
        "BSH.Common.Setting.AllowBackendConnection",
        "BSH.Common.Setting.AllowConsumerInsights",
        "BSH.Common.Setting.NetworkInterface",
        "BSH.Common.Setting.SynchronizeWithTimeServer",
        "BSH.Common.Status.BackendConnected",
        "BSH.Common.Status.CustomerServiceConnected",
        "BSH.Common.Status.LocalControlActive",
        "BSH.Common.Status.RemoteControlActive",
        "BSH.Common.Status.RemoteControlStartAllowed",
        "BSH.Common.Status.SoftwareUpdateTransactionID",
        "BSH.Common.Status.WiFiSignalStrength",
    }
)

# Readings with an entity of their own, made somewhere that knows what they
# mean. The door is a door rather than a word, and one reading is worth one
# entity, so it is not also made into a plain one here.
SPOKEN_FOR = frozenset({"BSH.Common.Status.DoorState"})

# The one setting that is never configuration. Switching an appliance on is
# the first thing anyone wants of it, and burying it under Configuration with
# the language and the date format helps nobody.
POWER_STATE = "BSH.Common.Setting.PowerState"

# What the serial number is written into. An appliance id is the brand, the
# model and the serial run together, and the last of the three is the only
# part that names one particular machine.
SERIAL = 2


def serial_of(haid: str) -> str | None:
    """The serial number out of an appliance id, if it is written that way."""
    parts = haid.split("-")
    return parts[SERIAL] if len(parts) > SERIAL else None


def device_info(appliance: Appliance) -> DeviceInfo:
    """The appliance, as Home Assistant keeps track of a thing.

    The model is the type code on the rating plate, which is what a manual or
    a spare part is looked up by. The full number with the customer index on
    the end is more precise and less recognisable, so it goes beside it rather
    than in place of it.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, appliance.id)},
        name=appliance.name,
        manufacturer=appliance.brand.title() or None,
        model=appliance.vib or appliance.type or None,
        model_id=appliance.enumber or None,
        serial_number=appliance.serial or serial_of(appliance.id),
    )


class HomeConnectEntity(CoordinatorEntity[HomeConnectCoordinator]):
    """Something about one appliance, whether or not it is a key of it."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeConnectCoordinator, haid: str) -> None:
        super().__init__(coordinator)
        self._haid = haid
        self._attr_device_info = device_info(coordinator.data[haid])

    @property
    def appliance(self) -> Appliance | None:
        return self.coordinator.data.get(self._haid)

    @property
    def available(self) -> bool:
        appliance = self.appliance
        return super().available and appliance is not None and appliance.connected


class KeyEntity(HomeConnectEntity):
    """One key of one appliance, of whichever of the three kinds it is."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, key: str, kind: str
    ) -> None:
        super().__init__(coordinator, haid)
        self._key = key
        self._kind = kind
        self._attr_unique_id = f"{haid}-{key}"
        self._attr_name = names.readable(key)
        self._attr_entity_category = _category(coordinator, haid, key, kind)

    @property
    def described(self) -> Feature | None:
        """What the appliance said this key will take, where it said anything.

        A status is never described beyond what it currently holds, and an
        option is only described while the programme it belongs to is set.
        """
        appliance = self.appliance
        if appliance is None:
            return None
        if self._kind == SETTING:
            return appliance.model.settings.get(self._key)
        if self._kind == OPTION:
            return appliance.any_option(self._key)
        return None

    @property
    def reading(self) -> Reading | None:
        """What the appliance last said this key is holding."""
        appliance = self.appliance
        if appliance is None:
            return None
        if self._kind == SETTING:
            return appliance.settings.get(self._key)
        if self._kind == OPTION:
            # An option held back until the programme starts has not been sent
            # anywhere, so the appliance still reports whatever it had before.
            # What was asked for is what to show, or nobody can see what they
            # have set the delayed start to.
            if self._key in appliance.pending:
                return Reading(value=appliance.pending[self._key])
            return appliance.options.get(self._key)
        return appliance.status.get(self._key)

    @property
    def held(self) -> Any:
        """The value itself, as the appliance writes it.

        Not called value: a number entity has one of its own that Home
        Assistant will not have overridden.
        """
        found = self.reading
        return None if found is None else found.value

    @property
    def shown(self) -> str | None:
        """What to call the value it is holding.

        The cloud names the value in the user's own language and that is what
        gets used. Where it has not, the key of the value says what it is well
        enough to read, and a value that is not a key is its own name.
        """
        found = self.reading
        if found is None or found.value is None:
            return None
        if found.shown:
            return found.shown
        described = self.described
        if described is not None and described.shown:
            named = described.shown.get(found.value)
            if named:
                return named
        if isinstance(found.value, str) and "." in found.value:
            return names.label(found.value)
        return str(found.value)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self._kind != OPTION:
            return True
        # An option belongs to a programme, so it is there for as long as that
        # programme is what the appliance is set to and no longer.
        appliance = self.appliance
        return appliance is not None and self._key in appliance.option_keys


class SettableEntity(KeyEntity):
    """A key the appliance will let us write, when it is in the mood.

    An appliance takes instructions only once remote control has been armed at
    the machine itself, and it says so. Nothing here can arm it, so a key that
    cannot be written now is shown as unavailable rather than offered and then
    refused.
    """

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        appliance = self.appliance
        if appliance is None:
            return False
        if self._kind == OPTION and not appliance.remote_control:
            return False
        described = self.described
        return described is not None and described.writable

    async def apply(self, value: Any) -> None:
        """Send a value back to the appliance.

        An appliance refuses what it will not do right now and says why: a
        door that is open, a cycle that has started, remote control that has
        not been armed. That reason is the only thing that tells whoever
        pressed the button what to go and do about it, so it is passed on
        rather than left in the log.
        """
        try:
            if self._kind == SETTING:
                await self.coordinator.apply_setting(self._haid, self._key, value)
            else:
                await self.coordinator.apply_option(self._haid, self._key, value)
        except HomeConnectError as err:
            raise HomeAssistantError(str(err)) from err


type Fields = Callable[[HomeConnectCoordinator], Iterator[tuple[str, str]]]
type Make = Callable[[HomeConnectCoordinator, str, str], Entity]


def follow(
    entry: ConfigEntry,
    coordinator: HomeConnectCoordinator,
    add: AddEntitiesCallback,
    fields: Fields,
    make: Make,
) -> None:
    """Make an entity for every key of this kind, now and as they turn up."""
    seen: set[tuple[str, str]] = set()

    @callback
    def look() -> None:
        appeared = [one for one in fields(coordinator) if one not in seen]
        if not appeared:
            return
        seen.update(appeared)
        add(make(coordinator, haid, key) for haid, key in appeared)

    look()
    entry.async_on_unload(coordinator.async_add_listener(look))


def _category(
    coordinator: HomeConnectCoordinator, haid: str, key: str, kind: str
) -> EntityCategory | None:
    """Where on the appliance's page this key belongs.

    A setting is the appliance's own housekeeping unless it is measured in
    something, which is what tells the temperature a fridge is held at from
    the language its display is in. What it is doing, and what the programme
    it is running can be adjusted by, are never housekeeping.
    """
    if key in DIAGNOSTIC:
        return EntityCategory.DIAGNOSTIC
    if kind != SETTING or key == POWER_STATE:
        return None
    described = coordinator.data[haid].model.settings.get(key)
    if described is not None and described.unit:
        return None
    return EntityCategory.CONFIG


def settings(
    coordinator: HomeConnectCoordinator, platform: str
) -> Iterator[tuple[str, str]]:
    """Every setting on the account that belongs to one platform.

    Less the ones that are part of a lamp, which is one thing made of three
    and is put together by the light platform instead.
    """
    for haid, appliance in coordinator.data.items():
        for key, described in appliance.model.settings.items():
            if key not in GATHERED and platform_for(described) == platform:
                yield haid, key


def options(
    coordinator: HomeConnectCoordinator, platform: str
) -> Iterator[tuple[str, str]]:
    """Every option of every programme seen so far, on one platform.

    An option is kept once it has been seen, because the programme it belongs
    to can be chosen again, and an entity that comes and goes with the
    programme is one that cannot be put on a dashboard.
    """
    for haid, appliance in coordinator.data.items():
        for described in _every_option(appliance):
            if platform_for(described) == platform:
                yield haid, described.key


def _every_option(appliance: Appliance) -> Iterable[Feature]:
    """Each option of each programme this appliance has described, once."""
    seen: set[str] = set()
    for options_of in appliance.model.options.values():
        for key, described in options_of.items():
            if key not in seen:
                seen.add(key)
                yield described


def statuses(
    coordinator: HomeConnectCoordinator, wanted_boolean: bool
) -> Iterator[tuple[str, str]]:
    """Every reading an appliance makes about itself, split by what it holds.

    Nothing describes a status beyond what it is holding, so what it holds is
    the only thing that says whether it is a flag or a reading. One holding
    nothing at all has not said yet, and waiting until it does is better than
    guessing and making an entity of the wrong kind that can never be unmade.
    """
    for haid, appliance in coordinator.data.items():
        for key, found in appliance.status.items():
            if found.value is None or key in SPOKEN_FOR:
                continue
            if isinstance(found.value, bool) == wanted_boolean:
                yield haid, key
