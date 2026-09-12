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

"""Local control, and the two things it needs that the cloud does not do.

An appliance talked to directly says everything in numbers. What each number
means comes from its description file, and this turns the pair of them into
exactly the shapes the cloud half produces, so that everything above stays
one code path and one set of entities whichever way the appliance is reached.

The other thing is finding it. An appliance shouts its address on the local
network, and that is the only place its address is written down: the account
knows which appliances exist and nothing about where they are.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from homeassistant.core import HomeAssistant, callback
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from .capability import OPTION, SETTING, STATUS, Feature, Reading
from .content import content
from .errors import HomeConnectError
from .http import hidden_id
from .iddf import Entry, named_value, uids_by_key, unpack
from .measures import unit_of

_LOGGER = logging.getLogger(__name__)

SERVICE = "_homeconnect._tcp.local."

# What a description calls each kind of thing, against what this does. A
# programme is not a feature to be read or set, so it is not in here: what
# programmes an appliance has is a different question, asked elsewhere.
KINDS = {
    "status": STATUS,
    "setting": SETTING,
    "option": OPTION,
    "event": "event",
    "command": "command",
}

# How long to give an appliance to answer when asked where it is.
RESOLVE = 5.0

# How long to sit on a newly heard address before writing it down. It only has
# to outlast the burst of announcements that arrive when an appliance wakes.
REMEMBER_AFTER = 30.0


def _feature(entry: Entry, kind: str) -> Feature:
    """One numbered thing, described the way the cloud describes the same one.

    An enumeration becomes the list of keys its members stand for, which is
    what the cloud sends. There are no translated names to go with them, the
    description file having none, so they read as the keys say.
    """
    named, carried = content(entry.content) or ("", "")
    return Feature(
        key=entry.key,
        kind=kind,
        # What the description says it is. Where it says nothing, a thing
        # with neither members nor a range still holds true or false.
        type=carried
        or ("Boolean" if not entry.values and entry.minimum is None else ""),
        unit=unit_of(named),
        access=entry.access,
        values=tuple(entry.values.values()),
        minimum=entry.minimum,
        maximum=entry.maximum,
        step=entry.step,
        execution=entry.execution,
    )


# Where an appliance keeps what it is doing and what it is set to do. Both
# hold the number of a programme rather than a value of their own, which is
# the one place a value has to be read as a reference to something else.
ACTIVE_PROGRAM = "BSH.Common.Root.ActiveProgram"
SELECTED_PROGRAM = "BSH.Common.Root.SelectedProgram"
PROGRAM_SLOTS = frozenset({ACTIVE_PROGRAM, SELECTED_PROGRAM})

# What the schema calls a thing that holds another thing's number. A hob has
# eighteen of them, three to a zone, and every one is a programme.
PROGRAM_REFERENCE = "uidValue"


@dataclass
class Described:
    """What an appliance can do, out of its description file."""

    settings: dict[str, Feature] = field(default_factory=dict)
    # By programme, the way the cloud describes options, so that what an
    # entity is offered follows what the appliance is set to.
    options: dict[str, dict[str, Feature]] = field(default_factory=dict)
    commands: tuple[str, ...] = ()
    programs: tuple[str, ...] = ()


def _refined(root: Entry, over: Entry) -> Entry:
    """A root option narrowed by what a programme says about it.

    A programme may cap the range or shorten the list of choices. What the
    thing is measured in and what sort of thing it is are the root's and do
    not move between programmes, so those are kept and only the parts the
    programme restated are taken from it.
    """
    return replace(
        root,
        minimum=over.minimum if over.minimum is not None else root.minimum,
        maximum=over.maximum if over.maximum is not None else root.maximum,
        step=over.step if over.step is not None else root.step,
        values=over.values or root.values,
        access=over.access,
        under=over.under,
    )


def describe(entries: dict[int, Entry]) -> Described:
    """Sort a description into the things the rest of this wants.

    An option written inside a programme belongs to that programme and refines
    the root option of the same name: a tighter range, or a shorter list of
    choices. An option no programme names at all belongs to all of them, which
    is how a description that does not bother to say says it. So each programme
    is handed the options it names, laid over the root for what they leave
    unsaid, together with the ones no programme claims.
    """
    described = Described()
    commands: list[str] = []
    programs: dict[int, str] = {}
    options: dict[int | None, dict[str, Entry]] = {}
    for entry in entries.values():
        kind = KINDS.get(entry.kind)
        if kind == SETTING:
            described.settings[entry.key] = _feature(entry, SETTING)
        elif kind == OPTION:
            options.setdefault(entry.under, {})[entry.key] = entry
        elif kind == "command":
            commands.append(entry.key)
        elif entry.kind == "program" and entry.available:
            programs[entry.uid] = entry.key
    everywhere = options.get(None, {})
    claimed = {name for uid in programs for name in options.get(uid, {})}
    shared = {name: e for name, e in everywhere.items() if name not in claimed}
    for uid, key in programs.items():
        merged = {name: _feature(entry, OPTION) for name, entry in shared.items()}
        for name, refinement in options.get(uid, {}).items():
            root = everywhere.get(name)
            narrowed = _refined(root, refinement) if root is not None else refinement
            merged[name] = _feature(narrowed, OPTION)
        described.options[key] = merged
    described.commands = tuple(sorted(commands))
    described.programs = tuple(sorted(programs.values()))
    return described


@dataclass
class Sorted:
    """What an appliance is holding, sorted the way the cloud sorts it."""

    status: dict[str, Reading] = field(default_factory=dict)
    settings: dict[str, Reading] = field(default_factory=dict)
    options: dict[str, Reading] = field(default_factory=dict)
    events: dict[str, Reading] = field(default_factory=dict)
    # Which programme is running and which is set, where either was said.
    active: str | None = None
    selected: str | None = None
    # Whether the appliance spoke of each slot at all in what it just sent. A
    # slot it said nothing about is left as it was; one it emptied is emptied,
    # which a bare None on its own cannot tell apart from silence.
    active_said: bool = False
    selected_said: bool = False


def sort(entries: dict[int, Entry], values: dict[int, Any]) -> Sorted:
    """Turn numbers and their values into keys and readings.

    A number the description never mentioned is dropped. There is nothing to
    call it and nothing to say what its value means, so an entity made from
    one would be a row of digits with a number for a name.
    """
    found = Sorted()
    for uid, value in values.items():
        entry = entries.get(uid)
        if entry is None:
            _LOGGER.debug("the appliance mentioned %s, which it never described", uid)
            continue
        if entry.key in PROGRAM_SLOTS:
            # These hold the number of a programme rather than a value of
            # their own. Nothing means no programme, which is what an
            # appliance sitting idle says.
            running = entries.get(value) if isinstance(value, int) else None
            named = running.key if running is not None else None
            if entry.key == ACTIVE_PROGRAM:
                found.active = named
                found.active_said = True
            else:
                found.selected = named
                found.selected_said = True
            continue
        named, _ = content(entry.content) or ("", "")
        if named == PROGRAM_REFERENCE:
            # A zone's own slots, and anything else holding the number of a
            # programme rather than a value of its own. Read the same way as
            # the two root slots: the programme's key, or nothing for none.
            referenced = entries.get(value) if isinstance(value, int) else None
            reading = Reading(value=referenced.key if referenced else None)
        else:
            reading = Reading(value=named_value(entry, value), unit=unit_of(named))
        kind = KINDS.get(entry.kind)
        if kind == STATUS:
            found.status[entry.key] = reading
        elif kind == SETTING:
            found.settings[entry.key] = reading
        elif kind == OPTION:
            found.options[entry.key] = reading
        elif kind == "event":
            found.events[entry.key] = reading
    return found


def _preferred(addresses: list[str]) -> str | None:
    """The address most likely to answer, out of what an appliance shouts.

    An IPv4 address before any IPv6 one, because a home network routes it
    where it may not route to an appliance's own IPv6, and a link-local IPv6
    last of all, since reaching one needs a scope the connection does not
    carry. An appliance that offers only IPv6 is still reached by it.
    """
    if not addresses:
        return None

    def rank(address: str) -> int:
        host = address.split("%", 1)[0].lower()
        if ":" not in host:
            return 0
        return 2 if host.startswith(("fe8", "fe9", "fea", "feb")) else 1

    return min(addresses, key=rank)


def _plainly(text: str) -> str:
    """A name with the punctuation taken out, for comparing one to another."""
    return "".join(letter for letter in text.lower() if letter.isalnum())


@dataclass(frozen=True)
class Where:
    """Where one appliance is, as it shouted it."""

    host: str
    port: int


class Finder:
    """Listens for appliances shouting their address on the local network.

    An appliance is matched to the account's idea of it by its identifier
    turning up somewhere in what it shouts: in the service name, in the name
    of the machine, or in one of the fields beside them. Which of the three
    differs between models, and reading all of them costs nothing.
    """

    def __init__(self, hass: HomeAssistant, on_found: Callable[[], None]) -> None:
        self._hass = hass
        self._on_found = on_found
        self._browser: AsyncServiceBrowser | None = None
        self._found: dict[str, Where] = {}

    async def start(self) -> None:
        from homeassistant.components import zeroconf

        instance = await zeroconf.async_get_async_instance(self._hass)
        self._browser = AsyncServiceBrowser(
            instance.zeroconf, [SERVICE], handlers=[self._changed]
        )

    async def stop(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            await browser.async_cancel()

    def where(self, haid: str) -> Where | None:
        """Where an appliance is, if it has been heard from."""
        wanted = _plainly(haid)
        for shouted, where in self._found.items():
            if wanted in shouted or shouted in wanted:
                return where
        return None

    @callback
    def _changed(
        self,
        zeroconf: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is ServiceStateChange.Removed:
            # An appliance that stops announcing keeps its last address rather
            # than being dropped: it shouts when it feels like it, and a kept
            # address is what reaches one gone quiet. A move announces itself
            # as a change, which resolves afresh and overwrites the address.
            return
        self._hass.async_create_task(self._ask(zeroconf, service_type, name))

    async def _ask(self, zeroconf: Any, service_type: str, name: str) -> None:
        """Ask an appliance that has just spoken where exactly it is."""
        info = AsyncServiceInfo(service_type, name)
        try:
            async with asyncio.timeout(RESOLVE + 1):
                if not await info.async_request(zeroconf, RESOLVE * 1000):
                    return
        except TimeoutError:
            return
        where = _preferred(info.parsed_scoped_addresses())
        if where is None or info.port is None:
            return
        said = [name, info.server or ""]
        said += [
            value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
            for value in (info.properties or {}).values()
            if value is not None
        ]
        self._found[_plainly(" ".join(said))] = Where(where, info.port)
        _LOGGER.debug("%s is at %s port %s", name, where, info.port)
        self._on_found()


@dataclass
class Known:
    """What is needed to talk to one appliance directly."""

    key: str
    iv: str | None
    entries: dict[int, Entry]
    # Where it was last found. An appliance shouts its address when it feels
    # like it and not when asked, so one that is quiet at the moment Home
    # Assistant starts would otherwise never be reached at all, however
    # reachable it is.
    where: Where | None = None

    def as_stored(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "iv": self.iv,
            "host": self.where.host if self.where else None,
            "port": self.where.port if self.where else None,
            "entries": {
                str(uid): {
                    "kind": entry.kind,
                    "key": entry.key,
                    "access": entry.access,
                    "available": entry.available,
                    "values": {str(k): v for k, v in entry.values.items()},
                    "minimum": entry.minimum,
                    "maximum": entry.maximum,
                    "step": entry.step,
                    "execution": entry.execution,
                    "content": entry.content,
                    "static": entry.static,
                    "under": entry.under,
                }
                for uid, entry in self.entries.items()
            },
        }

    @classmethod
    def from_stored(cls, stored: Any) -> Known | None:
        """Read one back, or nothing at all if it does not read."""
        if not isinstance(stored, dict):
            return None
        try:
            host = stored.get("host")
            return cls(
                key=str(stored["key"]),
                iv=stored["iv"],
                where=Where(str(host), int(stored["port"])) if host else None,
                entries={
                    int(uid): Entry(
                        uid=int(uid),
                        kind=str(one["kind"]),
                        key=str(one["key"]),
                        access=str(one["access"]),
                        available=bool(one["available"]),
                        values={int(k): str(v) for k, v in one["values"].items()},
                        minimum=one["minimum"],
                        maximum=one["maximum"],
                        step=one["step"],
                        execution=one["execution"],
                        # Written down since 0.1.1. One stored before that
                        # has none, and reads as an appliance that never
                        # said what its numbers are.
                        content=one.get("content"),
                        # The fixed value, where the description gave one.
                        static=one.get("static"),
                        # The programme a per-programme refinement sits under.
                        # Absent on anything stored before this and on every
                        # root thing, both of which read as under no programme.
                        under=one.get("under"),
                    )
                    for uid, one in stored["entries"].items()
                },
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            _LOGGER.debug("a stored appliance description no longer reads")
            return None


class LocalControl:
    """Every appliance on the account, talked to directly.

    What each appliance needs is fetched from the account once and kept: the
    key, which never changes, and the description, which changes only when the
    appliance's own software does. After that nothing here talks to the cloud
    at all.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: Any,
        account: Any,
        store: Any,
        on_values: Callable[[str, dict[int, Any]], None],
        on_connected: Callable[[str, bool], None],
        identity: str = "homeassistant",
    ) -> None:
        self._hass = hass
        # Who this says it is to every appliance. One connection is allowed
        # per identity, so two of these on one network reaching the same
        # appliance must not say the same thing, and this is what keeps them
        # apart.
        self._identity = identity
        self._session = session
        self._account = account
        self._store = store
        self._on_values = on_values
        self._on_connected = on_connected
        self._known: dict[str, Known] = {}
        self._links: dict[str, Any] = {}
        self._finder = Finder(hass, self._look_again)
        self._spawn: Callable[[Any], Any] | None = None

    async def load(self) -> None:
        """Read back what was learnt about these appliances last time."""
        stored = await self._store.async_load() or {}
        for haid, one in stored.items():
            known = Known.from_stored(one)
            if known is not None:
                self._known[haid] = known
        _LOGGER.debug("read back what is needed for %d appliances", len(self._known))

    async def learn(self, haids: list[str]) -> None:
        """Ask the account for whatever is not known yet.

        The key and the description both come one appliance at a time, so an
        account of six appliances costs twelve calls once and none thereafter.
        """
        wanted = [haid for haid in haids if haid not in self._known]
        if not wanted:
            return
        keys = await self._account.keys(wanted)
        _LOGGER.debug("the account named %d appliances with a key", len(keys))
        # Only an account with a key for nothing at all is refused. One that
        # already reaches an appliance this way and has gained one the cloud
        # holds no key for has one appliance to leave out, which the warning
        # below says, and not none to reach.
        if not keys and not self._known:
            raise HomeConnectError(
                "the account publishes no key for any appliance on it, so "
                "there is no way to reach one directly. Reach these "
                "appliances through the cloud instead"
            )
        for haid in wanted:
            secured = keys.get(haid)
            if secured is None:
                _LOGGER.warning("the account holds no key for %s", hidden_id(haid))
                continue
            try:
                entries = unpack(await self._account.description(haid))
            except HomeConnectError as err:
                # One appliance whose description will not read is one
                # appliance. Letting it stop here would take local control of
                # every other machine on the account down with it, the same
                # way one that answers nothing over the cloud does not stop
                # the rest being read.
                _LOGGER.warning(
                    "could not learn %s for local control: %s", hidden_id(haid), err
                )
                continue
            self._known[haid] = Known(
                key=secured["key"], iv=secured.get("iv"), entries=entries
            )
            _LOGGER.debug("learnt %d things about %s", len(entries), hidden_id(haid))
        await self._store.async_save(self._stored())

    def _stored(self) -> dict[str, Any]:
        return {haid: known.as_stored() for haid, known in self._known.items()}

    def _remember(self) -> None:
        """Write down where things are, without waiting on the disk.

        Discovery fires a callback, which cannot wait for a write, and an
        address heard a moment ago is not worth one of its own: whatever is
        written last is what is wanted, and a few seconds late will do.
        """
        self._store.async_delay_save(self._stored, REMEMBER_AFTER)

    def knows(self, haid: str) -> bool:
        return haid in self._known

    def entries(self, haid: str) -> dict[int, Entry]:
        known = self._known.get(haid)
        return known.entries if known else {}

    def described(self, haid: str) -> Described:
        return describe(self.entries(haid))

    def talking(self, haid: str) -> bool:
        link = self._links.get(haid)
        return bool(link and link.talking)

    async def start(self, spawn: Callable[[Any], Any]) -> None:
        self._spawn = spawn
        await self._finder.start()
        self._look_again()

    async def stop(self) -> None:
        # Forgotten first, so a resolution still in flight when the browser is
        # cancelled cannot come back through _look_again and open a link on an
        # appliance this control has already let go of.
        self._spawn = None
        await self._finder.stop()
        links, self._links = self._links, {}
        for link in links.values():
            await link.stop()

    @callback
    def _look_again(self) -> None:
        """Open a connection to anything found and not yet talked to there.

        An appliance already talked to is left alone unless it has started
        shouting from somewhere else. The link it has would go on reconnecting
        to where it was for good, so that one is let go of and another opened
        where the appliance is now.
        """
        if self._spawn is None:
            return
        for haid, known in self._known.items():
            # Where it is shouting from now, or where it was last heard
            # shouting from. An appliance shouts when it feels like it, so
            # waiting for one to shout again is waiting for nothing.
            found = self._finder.where(haid)
            link = self._links.get(haid)
            if link is not None and (found is None or found == known.where):
                continue
            where = found or known.where
            if where is None:
                continue
            if found is not None and found != known.where:
                self._known[haid] = replace(known, where=found)
                self._remember()
            if link is not None:
                self._spawn(link.stop())
            link = self._make(haid, known, where)
            self._links[haid] = link
            link.start(self._spawn)
            _LOGGER.debug(
                "talking to %s at %s, %s",
                hidden_id(haid),
                where.host,
                "where it is shouting from" if found else "where it last was",
            )

    def _make(self, haid: str, known: Known, where: Where) -> Any:
        from .hcp import HcpLink

        return HcpLink(
            self._session,
            where.host,
            known.key,
            known.iv,
            lambda values: self._on_values(haid, values),
            lambda talking: self._on_connected(haid, talking),
            identifier=self._identity,
            port=where.port,
        )

    async def write(self, haid: str, key: str, value: Any) -> None:
        """Set one thing on one appliance, by the key the rest of this uses."""
        link = self._links.get(haid)
        if link is None:
            raise HomeConnectError(f"{key} cannot be set while nothing is connected")
        entries = self.entries(haid)
        numbers = uids_by_key(entries)
        uid = numbers.get(key)
        if uid is None:
            raise HomeConnectError(f"this appliance has never heard of {key}")
        if key in PROGRAM_SLOTS:
            # These hold the number of a programme rather than a value, so
            # what goes back is the number of the programme being asked for.
            wanted = numbers.get(str(value))
            if wanted is None:
                raise HomeConnectError(f"this appliance has no programme {value}")
            await link.write(uid, wanted)
            return
        await link.write(uid, _as_sent(entries[uid], value))


def _as_sent(entry: Entry, value: Any) -> Any:
    """A value in the shape the appliance takes it in.

    An enumerated value goes back as the number of its member, which is the
    way round of what is done reading one.
    """
    if not entry.values or isinstance(value, bool):
        return value
    for number, named in entry.values.items():
        if named == value:
            return number
    return value
