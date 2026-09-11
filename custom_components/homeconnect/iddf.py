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

"""What an appliance is, as the appliance's own description file says.

Talked to directly, an appliance says nothing in words. Every setting, status
and programme is a number, and a value is a number beside it. The description
file is what turns those back into the keys the rest of this is written
against, and it is the one thing local control cannot do without.

It arrives from the cloud as a zip of two XML files. One maps each number to
the key it stands for and names the members of each enumeration; the other
says what kind of thing each number is and what it will take. They are joined
here into one table.

Nothing is read by where it sits in the file. Both are walked for elements
carrying the attribute that matters, so a file that gains a section, or lists
one in another order, still reads.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from .errors import HomeConnectError

_LOGGER = logging.getLogger(__name__)

# What the two members of the archive are called. Matched by ending rather
# than in full, the rest of the name being the appliance's own identifier.
MAPPING = "_FeatureMapping.xml"
DESCRIPTION = "_DeviceDescription.xml"

# The kinds of thing a description lists, by the element each is written as.
# Anything else carrying a number is skipped: a description also numbers
# things that are not features of the appliance.
# The elements that describe one numbered thing. The two programme slots are
# written as their own kinds rather than as entries in a list, and they are
# where an appliance says what it is running and what it is set to run, so a
# description read without them is one that cannot say either.
KINDS = frozenset(
    {
        "status",
        "setting",
        "command",
        "option",
        "event",
        "program",
        "activeProgram",
        "selectedProgram",
    }
)

# What an element that describes a feature calls its number, and what the
# elements that name one call theirs.
UID = "uid"
CONTENT = "refCID"
FEATURE = "refUID"
ENUM = "refENID"
ENUM_KEY = "enumKey"
MEMBER = "refValue"


def _number(written: str | None) -> int | None:
    """A number as the description writes them, which is in hexadecimal."""
    if not written:
        return None
    try:
        return int(written, 16)
    except ValueError:
        return None


def _figure(written: str | None) -> float | None:
    if written is None:
        return None
    try:
        return float(written)
    except ValueError:
        return None


@dataclass(frozen=True)
class Entry:
    """One numbered thing an appliance has."""

    uid: int
    kind: str
    key: str
    access: str = "read"
    available: bool = True
    # The members of its enumeration, by the number each is sent as.
    values: dict[int, str] = field(default_factory=dict)
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    execution: str | None = None
    # What the thing is, as the number the description gives it. The
    # description says how large a thing may be and never what it is, so
    # this is what tells a length of time from a plain figure.
    content: int | None = None
    # The programme this sits inside, where it sits inside one. An option
    # written under a programme belongs to that programme and to no other.
    under: int | None = None

    @property
    def readable(self) -> bool:
        return "read" in self.access.lower()

    @property
    def writable(self) -> bool:
        return "write" in self.access.lower()


def _named(
    mapping: ElementTree.Element,
) -> tuple[dict[int, str], dict[int, dict[int, str]]]:
    """What each number is called, and what each enumeration's members are.

    A member is written as its own last word, under an enumeration carrying
    the rest of the key. They are put back together here, so that a value read
    off an appliance directly is spelled the way the same value is spelled
    everywhere else in this integration.
    """
    keys: dict[int, str] = {}
    for element in mapping.iter():
        uid = _number(element.get(FEATURE))
        if uid is not None and element.text:
            keys[uid] = element.text.strip()

    enums: dict[int, dict[int, str]] = {}
    for element in mapping.iter():
        enum = _number(element.get(ENUM))
        if enum is None:
            continue
        under = (element.get(ENUM_KEY) or "").strip()
        members: dict[int, str] = {}
        for member in element:
            written = member.get(MEMBER)
            if written is None or not member.text:
                continue
            leaf = member.text.strip()
            try:
                members[int(written)] = f"{under}.{leaf}" if under else leaf
            except ValueError:
                continue
        enums[enum] = members
    return keys, enums


def _entry(
    element: ElementTree.Element,
    uid: int,
    keys: dict[int, str],
    enums: dict[int, dict[int, str]],
    under: int | None,
) -> Entry | None:
    key = keys.get(uid)
    if key is None:
        # A number the description lists and the mapping never names. There
        # is nothing to call it, so there is nothing to make of it.
        return None
    enum = _number(element.get("enumerationType"))
    return Entry(
        under=under,
        uid=uid,
        kind=element.tag.rpartition("}")[2],
        key=key,
        content=_number(element.get(CONTENT)),
        access=str(element.get("access") or "read"),
        available=str(element.get("available", "true")).lower() != "false",
        values=dict(enums.get(enum) or {}) if enum is not None else {},
        minimum=_figure(element.get("min")),
        maximum=_figure(element.get("max")),
        step=_figure(element.get("stepSize")),
        execution=element.get("execution"),
    )


def parse(mapping_xml: bytes, description_xml: bytes) -> dict[int, Entry]:
    """Join the two halves into one table, by the number they share."""
    try:
        mapping = ElementTree.fromstring(mapping_xml)
        description = ElementTree.fromstring(description_xml)
    except ElementTree.ParseError as err:
        raise HomeConnectError(
            f"the appliance description does not read: {err}"
        ) from err

    keys, enums = _named(mapping)
    entries: dict[int, Entry] = {}

    def walk(element: ElementTree.Element, under: int | None) -> None:
        """Down the tree, remembering the programme anything sits inside.

        A description that writes its options under the programmes they
        belong to is saying which belongs to which, and that is worth
        keeping. One that writes them all in a list of their own is saying
        they belong to everything, which is what no programme means.
        """
        for child in element:
            tag = child.tag.rpartition("}")[2]
            uid = _number(child.get(UID))
            inside = under
            if tag in KINDS and uid is not None:
                found = _entry(child, uid, keys, enums, under)
                if found is not None:
                    entries[uid] = found
                if tag == "program":
                    inside = uid
            walk(child, inside)

    walk(description, None)
    if not entries:
        raise HomeConnectError("the appliance description named nothing")
    _LOGGER.debug("the description covers %d things", len(entries))
    return entries


def unpack(archive: bytes) -> dict[int, Entry]:
    """The table, out of the zip the cloud hands over."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = bundle.namelist()
            mapping = next((one for one in names if one.endswith(MAPPING)), None)
            description = next(
                (one for one in names if one.endswith(DESCRIPTION)), None
            )
            if mapping is None or description is None:
                raise HomeConnectError(
                    f"the description archive holds {names} and not the two "
                    "files an appliance is described by"
                )
            return parse(bundle.read(mapping), bundle.read(description))
    except zipfile.BadZipFile as err:
        raise HomeConnectError(f"the description is not an archive: {err}") from err


def files(archive: bytes) -> dict[str, str]:
    """The two XML files out of the zip, as they were written.

    What was parsed is what this integration made of the description. What
    was sent is the description itself, and only that can say whether
    something missing was never there or was dropped on the way in.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            # Keyed by which of the two it is, never by the name it was
            # filed under: that is the appliance's identifier with the kind
            # stuck on the end, and the identifier names one household.
            return {
                kind.lstrip("_"): bundle.read(name).decode("utf-8", errors="replace")
                for name in bundle.namelist()
                for kind in (MAPPING, DESCRIPTION)
                if name.endswith(kind)
            }
    except zipfile.BadZipFile as err:
        raise HomeConnectError(f"the description is not an archive: {err}") from err


def keys_by_uid(entries: dict[int, Entry]) -> dict[int, str]:
    return {uid: entry.key for uid, entry in entries.items()}


def uids_by_key(entries: dict[int, Entry]) -> dict[str, int]:
    """The way back, for sending something to the appliance.

    A key names one thing, so where a description numbers the same key twice
    the first stands. Nothing has been seen doing that; it is written this way
    so that one doing it loses a duplicate rather than the lot.
    """
    found: dict[str, int] = {}
    for uid, entry in entries.items():
        found.setdefault(entry.key, uid)
    return found


def named_value(entry: Entry, value: Any) -> Any:
    """A value as the rest of this writes them.

    An enumerated value arrives as the number of its member, and the key it
    stands for is the enumeration's own key with the member on the end, which
    is how every other part of this spells one.
    """
    if not entry.values or not isinstance(value, int) or isinstance(value, bool):
        return value
    member = entry.values.get(value)
    if member is None:
        return value
    return member
