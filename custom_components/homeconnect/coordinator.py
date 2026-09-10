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

"""Keeping one account's appliances up to date.

Two kinds of thing arrive from the cloud and they age very differently. What a
model of appliance can do is fixed: which settings it has, what each will take,
what a programme can be adjusted by. What it is doing changes by the minute.
The first is read once and kept between restarts, because reading it costs a
call for every setting an appliance has and the answer would be the same every
time. The second is pushed as it happens and only polled as a backstop.

The cloud counts every call against a quota, so the aim throughout is to ask
as little as possible: the stream carries the changes, and a fresh look is
only arranged when something happened that the stream cannot describe.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ACTIVE, SELECTED, HomeConnectApi
from .capability import OPTION, SETTING, Feature, Reading, feature, reading
from .const import DOMAIN
from .errors import (
    HomeConnectAuthError,
    HomeConnectError,
    HomeConnectTooManyRequests,
)
from .events import Event

_LOGGER = logging.getLogger(__name__)

# Bump when what is kept between restarts would no longer be understood.
# Anything written under another version is thrown away rather than migrated,
# so the next start reads it again instead of trusting it.
STORE_VERSION = 1

# Where an appliance says what it is doing and whether it is on. A change to
# either moves what it will accept, which is not something the stream
# describes, so it is worth another look when one of them moves.
OPERATION_STATE = "BSH.Common.Status.OperationState"
POWER_STATE = "BSH.Common.Setting.PowerState"
DOOR_STATE = "BSH.Common.Status.DoorState"
REMOTE_CONTROL = "BSH.Common.Status.RemoteControlActive"
REMOTE_START = "BSH.Common.Status.RemoteControlStartAllowed"

# Where the two programme slots are reported when they change. The stream
# names them this way; the API calls the same two things active and selected.
ACTIVE_PROGRAM = "BSH.Common.Root.ActiveProgram"
SELECTED_PROGRAM = "BSH.Common.Root.SelectedProgram"

# What a change to one of these is a sign of: the appliance has moved into a
# state where a different set of programmes and options applies.
UNSETTLING = frozenset(
    {ACTIVE_PROGRAM, SELECTED_PROGRAM, OPERATION_STATE, POWER_STATE, DOOR_STATE}
)

# Long enough that a burst of events arriving together, which is what the end
# of a cycle looks like, costs one look rather than six.
SETTLE = 3.0

SCAN_INTERVAL = timedelta(minutes=1)
# Once the cloud is really pushing, polling is only there to catch what a
# dropped connection missed.
SCAN_INTERVAL_STREAMING = timedelta(minutes=30)


class ModelStore(Store[dict[str, Any]]):
    """What each model of appliance can do, kept between starts.

    Nothing in here is worth migrating. Anything written under a version that
    read it differently is thrown away and asked for again, which costs a
    handful of calls once and is the whole point of the version above.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep nothing, so that everything is read afresh."""
        return {}


def model_store(hass: HomeAssistant, entry: ConfigEntry) -> ModelStore:
    """Where an account's model descriptions are kept between starts."""
    return ModelStore(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.models")


@dataclass
class Model:
    """What one model of appliance can do, which does not change.

    Held apart from what the appliance is doing, because the two are read at
    different times and only this half is worth keeping.
    """

    settings: dict[str, Feature] = field(default_factory=dict)
    commands: tuple[str, ...] = ()
    # By programme, since a programme decides what can be adjusted about it.
    options: dict[str, dict[str, Feature]] = field(default_factory=dict)
    # Whether an appliance of this model has ever answered these questions. An
    # appliance that was switched off at the wall when this started answers
    # only that it exists, and an empty description is not an answer to keep.
    described: bool = False

    def as_stored(self) -> dict[str, Any]:
        return {
            "settings": _stored(self.settings),
            "commands": list(self.commands),
            "options": {
                program: _stored(options) for program, options in self.options.items()
            },
            "described": self.described,
        }

    @classmethod
    def from_stored(cls, stored: Any) -> Model | None:
        """Read one back, or nothing at all if it does not read.

        What is on disk was written by a version of this that may not be the
        one reading it. Anything that does not come back as it went in is
        dropped whole, and the appliance is asked again.
        """
        if not isinstance(stored, dict):
            return None
        try:
            return cls(
                settings=_restored(stored["settings"]),
                commands=tuple(str(key) for key in stored["commands"]),
                options={
                    str(program): _restored(options)
                    for program, options in stored["options"].items()
                },
                described=bool(stored["described"]),
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            _LOGGER.debug("a stored model description no longer reads, dropping it")
            return None


@dataclass
class Appliance:
    """One appliance, what it can do and what it is doing."""

    id: str
    name: str
    brand: str
    vib: str
    enumber: str
    type: str
    connected: bool
    model: Model
    status: dict[str, Reading] = field(default_factory=dict)
    settings: dict[str, Reading] = field(default_factory=dict)
    # An event is a thing that is either happening or not, so nothing
    # describes one beyond what it is doing at the moment.
    events: dict[str, Reading] = field(default_factory=dict)
    # The programmes on offer in the state the appliance is in now, and what
    # the cloud calls each of them in the user's own language.
    programs: tuple[str, ...] = ()
    program_names: dict[str, str] = field(default_factory=dict)
    active: str | None = None
    selected: str | None = None
    options: dict[str, Reading] = field(default_factory=dict)
    # Options that can only be given as a programme starts, held until it does.
    pending: dict[str, Any] = field(default_factory=dict)

    @property
    def program(self) -> str | None:
        """The programme the options belong to, which is what it is doing."""
        return self.active or self.selected

    @property
    def option_keys(self) -> tuple[str, ...]:
        """What the current programme can be adjusted by."""
        if self.program is None:
            return ()
        return tuple(self.model.options.get(self.program, {}))

    def option(self, key: str) -> Feature | None:
        """How one option of the current programme is described."""
        if self.program is None:
            return None
        return self.model.options.get(self.program, {}).get(key)

    def any_option(self, key: str) -> Feature | None:
        """How this option is described by whichever programme describes it.

        An entity for an option outlives the programme it first appeared
        under, so it needs something to say about itself while a programme
        that has never heard of it is selected. Any description will do for
        that: what it is measured in and what sort of thing it is do not move
        between programmes, and the parts that do are read from the programme
        actually in force.
        """
        found = self.option(key)
        if found is not None:
            return found
        for options_of in self.model.options.values():
            described = options_of.get(key)
            if described is not None:
                return described
        return None

    @property
    def running(self) -> bool:
        """Whether a programme is under way."""
        return self.active is not None

    @property
    def remote_start(self) -> bool:
        """Whether the appliance will let a programme be started from here.

        An appliance that says nothing about it has no such lock, and one that
        has is arming it at the machine itself, which nothing here can do.
        """
        told = self.status.get(REMOTE_START)
        return True if told is None else bool(told.value)

    @property
    def remote_control(self) -> bool:
        """Whether the appliance will take instructions from here at all."""
        told = self.status.get(REMOTE_CONTROL)
        return True if told is None else bool(told.value)


class HomeConnectCoordinator(DataUpdateCoordinator[dict[str, Appliance]]):
    """Holds the state of every appliance on one account."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: HomeConnectApi,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self._store = model_store(hass, entry)
        # By model, since two appliances of the same model can do the same
        # things and reading it twice is two sets of calls for one answer.
        self._models: dict[str, Model] = {}
        self._streaming = False
        self._settling: dict[str, CALLBACK_TYPE] = {}
        # Which of the appliances due another look need the whole of it rather
        # than only what it will run.
        self._thoroughly: set[str] = set()
        self._looking: set[str] = set()

    async def async_load_models(self) -> None:
        """Read back what was learnt about these models last time."""
        stored = await self._store.async_load() or {}
        for name, description in stored.items():
            model = Model.from_stored(description)
            if model is not None:
                self._models[name] = model
        _LOGGER.debug("read back %d model descriptions", len(self._models))

    async def _save_models(self) -> None:
        await self._store.async_save(
            {name: model.as_stored() for name, model in self._models.items()}
        )

    # Polling

    async def _async_update_data(self) -> dict[str, Appliance]:
        """Read the whole account, which is what a poll is for."""
        try:
            listed = await self.api.appliances()
        except HomeConnectAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HomeConnectTooManyRequests as err:
            # Being asked to slow down is not a failure. Keeping what we hold
            # is better than taking every entity away over one refused call.
            _LOGGER.debug("the cloud asked us to slow down: %s", err)
            if self.data:
                return self.data
            raise UpdateFailed(str(err)) from err
        except HomeConnectError as err:
            raise UpdateFailed(str(err)) from err

        appliances: dict[str, Appliance] = {}
        for described in listed:
            haid = str(described.get("haId") or "")
            if not haid:
                continue
            try:
                appliances[haid] = await self._read(haid, described)
            except HomeConnectAuthError as err:
                # The account itself, rather than this one appliance.
                raise ConfigEntryAuthFailed(str(err)) from err
            except HomeConnectError as err:
                # One appliance that will not answer is one appliance. Taking
                # the whole account away over it would take every other
                # machine in the house with it.
                _LOGGER.warning("could not read %s: %s", described.get("name"), err)
                held = (self.data or {}).get(haid)
                if held is not None:
                    appliances[haid] = held
        if not appliances and listed:
            raise UpdateFailed("no appliance on the account would answer")
        await self._save_models()
        return appliances

    async def _read(self, haid: str, described: dict[str, Any]) -> Appliance:
        """Everything about one appliance, as much of it as it will say.

        An appliance that is switched off at the wall answers the listing and
        nothing else, so what it last said is kept rather than blanked: it has
        not stopped having settings, it has only stopped answering about them.
        """
        held = (self.data or {}).get(haid)
        connected = bool(described.get("connected"))
        model = self._model(haid, described)
        appliance = Appliance(
            id=haid,
            name=str(described.get("name") or haid),
            brand=str(described.get("brand") or ""),
            vib=str(described.get("vib") or ""),
            enumber=str(described.get("enumber") or ""),
            type=str(described.get("type") or ""),
            connected=connected,
            model=model,
            pending=dict(held.pending) if held else {},
        )
        if not connected:
            if held is not None:
                appliance.status = held.status
                appliance.settings = held.settings
                appliance.events = held.events
                appliance.programs = held.programs
                appliance.program_names = held.program_names
                appliance.active = held.active
                appliance.selected = held.selected
                appliance.options = held.options
            return appliance
        await self._refresh(appliance)
        return appliance

    async def _refresh(self, appliance: Appliance) -> None:
        """What one appliance is doing, and what it can do at all.

        The second of those is asked once per model and kept, so this is
        where an appliance that was switched off at the wall when Home
        Assistant started gets described: the moment it answers, rather than
        whenever the next look round the account happens to come.
        """
        haid = appliance.id
        if not appliance.model.described:
            await self._describe(haid, appliance.model)
        appliance.status = _readings(await self.api.status(haid))
        appliance.settings = _readings(await self.api.settings(haid))
        appliance.events = _readings(await self.api.events(haid))
        await self._read_programs(appliance)

    async def _read_programs(self, appliance: Appliance) -> None:
        """Which programmes are on offer, which one is set, and its options."""
        haid = appliance.id
        offered = await self.api.available_programs(haid)
        appliance.programs = tuple(
            str(found["key"]) for found in offered if found.get("key")
        )
        active = await self.api.program(haid, ACTIVE)
        selected = await self.api.program(haid, SELECTED)
        appliance.program_names = _named(offered) | _named([active, selected])
        appliance.active = str(active["key"]) if active and active.get("key") else None
        appliance.selected = (
            str(selected["key"]) if selected and selected.get("key") else None
        )
        # Where both slots are filled they describe the same programme, and
        # what it is doing beats what it was set up to do.
        appliance.options = _option_values(selected) | _option_values(active)
        if appliance.program is not None:
            await self._read_options(appliance, appliance.program)

    async def _read_options(self, appliance: Appliance, program: str) -> None:
        """What one programme can be adjusted by, if we do not already know."""
        if program in appliance.model.options:
            return
        described = await self.api.program_options(appliance.id, program)
        appliance.model.options[program] = _features(described, OPTION)

    @callback
    def _model(self, haid: str, described: dict[str, Any]) -> Model:
        """Which description this appliance shares, made if it is new.

        Two appliances of the same model answer the same way, and what they
        answer does not change, so they share one description and it is filled
        in once. An appliance with no model number stands for itself.
        """
        name = str(described.get("enumber") or haid)
        model = self._models.get(name)
        if model is None:
            model = Model()
            self._models[name] = model
        return model

    async def _describe(self, haid: str, model: Model) -> None:
        """Ask an appliance what each of its settings will take.

        The listing gives the settings by name and nothing else, so this is a
        call for each one. It is the most expensive thing here and the reason
        the answer is kept between restarts.
        """
        for listed in await self.api.settings(haid):
            key = listed.get("key")
            if not isinstance(key, str):
                continue
            described = await self.api.setting(haid, key)
            found = feature(described or listed, SETTING)
            if found is not None:
                model.settings[key] = found
        model.commands = tuple(
            str(found["key"])
            for found in await self.api.commands(haid)
            if found.get("key")
        )
        model.described = True

    # What the stream says

    @callback
    def apply(self, event: Event) -> None:
        """Fold one pushed event into what we hold."""
        appliance = (self.data or {}).get(event.haid)
        if appliance is None:
            if event.name in ("PAIRED", "DEPAIRED"):
                # An appliance we have never seen, or one that has just gone.
                # Either way the listing is what settles it.
                self.hass.async_create_task(self.async_request_refresh())
            return
        if event.name == "CONNECTED":
            appliance.connected = True
            # It has been away, and what it says now is not what it said when
            # it went. Everything it reports is worth reading again, not just
            # what it will run.
            self._look_again(appliance.id, thoroughly=True)
        elif event.name == "DISCONNECTED":
            appliance.connected = False
        elif event.name == "DEPAIRED":
            self.hass.async_create_task(self.async_request_refresh())
            return
        else:
            self._apply_items(appliance, event)
        self.async_set_updated_data(self.data)

    @callback
    def _apply_items(self, appliance: Appliance, event: Event) -> None:
        """Write the values an event carries into the right list.

        Which list a key belongs to is written into the key itself, so an
        event does not have to say and never does.
        """
        unsettled = False
        for item in event.items:
            key = item.get("key")
            if not isinstance(key, str):
                continue
            value = item.get("value")
            if key == ACTIVE_PROGRAM:
                appliance.active = str(value) if value else None
                unsettled = True
            elif key == SELECTED_PROGRAM:
                appliance.selected = str(value) if value else None
                unsettled = True
            elif ".Event." in key:
                appliance.events[key] = reading(item)
            elif ".Status." in key:
                appliance.status[key] = reading(item)
            elif ".Setting." in key:
                appliance.settings[key] = reading(item)
            elif ".Option." in key:
                appliance.options[key] = reading(item)
            else:
                _LOGGER.debug("nothing here knows where %s belongs", key)
            if key in UNSETTLING:
                unsettled = True
        if unsettled:
            self._look_again(appliance.id)

    @callback
    def _look_again(self, haid: str, thoroughly: bool = False) -> None:
        """Arrange a fresh look at one appliance, once the dust has settled.

        What an appliance offers moves with what it is doing, and no event
        says so: a machine that has just been switched on has a list of
        programmes it did not have a moment ago. Several such events arrive
        together, so the look is put off until they stop.
        """
        if thoroughly:
            self._thoroughly.add(haid)
        cancel = self._settling.pop(haid, None)
        if cancel is not None:
            cancel()

        async def look(_now: Any) -> None:
            self._settling.pop(haid, None)
            deep = haid in self._thoroughly
            self._thoroughly.discard(haid)
            await self._look(haid, deep)

        self._settling[haid] = async_call_later(self.hass, SETTLE, look)

    async def _look(self, haid: str, thoroughly: bool) -> None:
        """Read one appliance again, and tell everyone what it said."""
        appliance = (self.data or {}).get(haid)
        if appliance is None or not appliance.connected or haid in self._looking:
            return
        self._looking.add(haid)
        try:
            if thoroughly:
                await self._refresh(appliance)
            else:
                await self._read_programs(appliance)
        except HomeConnectError as err:
            _LOGGER.debug("could not look at %s again: %s", appliance.name, err)
        finally:
            self._looking.discard(haid)
        self.async_set_updated_data(self.data)

    @callback
    def stop_settling(self) -> None:
        """Give up on every look that has not happened yet."""
        for cancel in self._settling.values():
            cancel()
        self._settling.clear()
        self._thoroughly.clear()

    # How often to ask

    @callback
    def set_streaming(self, streaming: bool) -> None:
        """Ask less often while the cloud is pushing, and more when it is not."""
        if streaming == self._streaming:
            return
        self._streaming = streaming
        self.update_interval = SCAN_INTERVAL_STREAMING if streaming else SCAN_INTERVAL
        _LOGGER.debug(
            "the event stream is %s, polling every %s",
            "up" if streaming else "down",
            self.update_interval,
        )
        if not streaming:
            # Whatever was missed while it was down is missed until something
            # asks, and the next scheduled poll is a long way off.
            self.hass.async_create_task(self.async_request_refresh())

    # Setting things, which every entity that can be set goes through

    async def apply_setting(self, haid: str, key: str, value: Any) -> None:
        """Change one of the appliance's own settings.

        The cloud pushes the change back a moment later, but only a moment,
        and an entity that has just been told to do something should not sit
        there showing what it was before. So what was asked for is written in
        straight away and the stream corrects it if the appliance disagreed.
        """
        await self.api.set_setting(haid, key, value)
        self.data[haid].settings[key] = _asked_for(
            self.data[haid].model.settings.get(key), value
        )
        self.async_set_updated_data(self.data)

    async def send_command(self, haid: str, key: str) -> None:
        """Tell the appliance to do something once."""
        await self.api.send_command(haid, key)
        self._look_again(haid)

    async def apply_option(self, haid: str, key: str, value: Any) -> None:
        """Set one option of the current programme.

        An option that can only be given as a programme starts is held here
        until it does, since the cloud takes it, answers as though it worked
        and quietly ignores it.
        """
        appliance = self.data[haid]
        described = appliance.option(key)
        if described is not None and described.start_only:
            appliance.pending[key] = value
            self.async_set_updated_data(self.data)
            return
        await self.api.set_option(
            haid, ACTIVE if appliance.running else SELECTED, key, value
        )
        appliance.options[key] = _asked_for(described, value)
        self.async_set_updated_data(self.data)

    async def select_program(self, haid: str, program: str) -> None:
        """Set the programme the appliance will run next."""
        appliance = self.data[haid]
        await self.api.set_program(haid, SELECTED, program, [])
        appliance.selected = program
        await self._read_options(appliance, program)
        self.async_set_updated_data(self.data)
        self._look_again(haid)

    async def start_program(self, haid: str) -> None:
        """Start whatever the appliance is set to do, with what was held back."""
        appliance = self.data[haid]
        program = appliance.selected
        if program is None:
            raise HomeConnectError("nothing is selected to start")
        options = [
            {"key": key, "value": value} for key, value in appliance.pending.items()
        ]
        await self.api.set_program(haid, ACTIVE, program, options)
        appliance.pending.clear()
        self._look_again(haid)

    async def stop_program(self, haid: str) -> None:
        """Stop whatever the appliance is doing."""
        await self.api.stop_program(haid)
        self._look_again(haid)


def _features(described: list[dict[str, Any]], kind: str) -> dict[str, Feature]:
    """A list of descriptions as the features they describe."""
    found = (feature(node, kind) for node in described)
    return {one.key: one for one in found if one is not None}


def _named(described: Sequence[dict[str, Any] | None]) -> dict[str, str]:
    """What the cloud calls each of these, where it said."""
    return {
        str(node["key"]): str(node["name"])
        for node in described
        if node and isinstance(node.get("key"), str) and node.get("name")
    }


def _readings(described: list[dict[str, Any]]) -> dict[str, Reading]:
    """A list of things the cloud reported, by the key of each."""
    return {
        str(node["key"]): reading(node)
        for node in described
        if isinstance(node.get("key"), str)
    }


def _option_values(program: dict[str, Any] | None) -> dict[str, Reading]:
    """What a programme reports for its own options."""
    if not program:
        return {}
    options = program.get("options")
    if not isinstance(options, list):
        return {}
    return _readings([option for option in options if isinstance(option, dict)])


def _asked_for(described: Feature | None, value: Any) -> Reading:
    """A reading standing for a value we have just sent.

    The appliance will report it back with its own name for it in a moment.
    Until then the name the description carries is the best there is, and
    where there is none the value stands for itself.
    """
    shown = described.shown.get(value) if described and described.shown else None
    return Reading(value=value, shown=shown, unit=described.unit if described else None)


def _stored(features: dict[str, Feature]) -> dict[str, Any]:
    """Descriptions in a shape that survives being written out and read back.

    Only the description is kept. What a setting happened to hold when it was
    first read is not something to remember for the next start, and writing it
    down invites showing it again months later as though it were the truth.
    """
    return {
        key: {
            name: (list(value) if isinstance(value, tuple) else value)
            for name, value in vars(found).items()
            if name != "value"
        }
        for key, found in features.items()
    }


def _restored(stored: Any) -> dict[str, Feature]:
    """Descriptions as they were written out, back as what they describe.

    Written down, a list of values is a list. Read back it has to be a tuple
    again, since a description is meant to be a thing that cannot change under
    whatever is holding it.
    """
    return {
        str(key): Feature(
            key=str(found["key"]),
            kind=str(found["kind"]),
            unit=found.get("unit"),
            type=str(found.get("type") or ""),
            access=str(found.get("access") or "read"),
            values=tuple(found.get("values") or ()),
            shown=found.get("shown"),
            minimum=found.get("minimum"),
            maximum=found.get("maximum"),
            step=found.get("step"),
            default=found.get("default"),
            execution=found.get("execution"),
        )
        for key, found in stored.items()
    }
