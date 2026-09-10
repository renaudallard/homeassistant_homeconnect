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

"""Readable names for the things an appliance talks about.

Every key is a path: which family of appliance it belongs to, which part of
the API it lives in, and then what it actually is. The last part is written in
camel case and says plainly what it means, so a name is worked out from it
rather than looked up, and a key nobody here has seen reads as well as one
that was written against.

Two kinds of text are wanted and they are not the same. A field needs a name
that stands on its own beside its appliance, so it keeps the whole descriptive
tail: Camera 1 enabled rather than Enabled. A value only needs to name itself
within the list it sits in, so it keeps the last part alone: Hot air rather
than Heating mode hot air.

The cloud offers its own text for both, translated, and where it does that is
what gets used. This is what happens when it does not, which is often enough
that it cannot be an afterthought.
"""

from __future__ import annotations

import re

# Which part of the API a key lives in, sitting between the family it belongs
# to and what it actually names.
KIND = re.compile(
    r"\.(?:Setting|Status|Option|OptionList|Command|Program|ProgramGroup"
    r"|EnumType|Event|Root|Group)\."
)

# Where one word ends and the next begins: at the capital that starts a word,
# at the capital that ends a run of them, and where a number starts. Written
# as places rather than as separators so that a run of capitals survives
# whole, which is what turns HHCStartupSetting into HHC startup setting and
# SoftwareUpdateTransactionID into one ending in ID.
CAMEL = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)"
)

# A number written into a key, whether as its own segment or on the end of a
# word: the 001 of Camera.001.Enabled and the 01 of LiftCustomerHeight01 both
# tell one of several apart, and both read better without the padding.
PADDED = re.compile(r"^0+(?=\d)")

# The cloud is written in American English and this is not. Only whole words
# are replaced, so nothing that merely starts with one of them is touched.
SPELLINGS = {
    "program": "programme",
    "programs": "programmes",
    "color": "colour",
    "colors": "colours",
}

# Keys whose own spelling gives a name nobody would recognise. Everything else
# is worked out, and this stays short on purpose: an entry here is a name that
# stops following the appliance the day the appliance changes its mind.
NAMES = {
    "BSH.Common.Root.ActiveProgram": "Active programme",
    "BSH.Common.Root.SelectedProgram": "Selected programme",
    "BSH.Common.Status.WiFiSignalStrength": "Wi-Fi signal strength",
    "LaundryCare.Washer.Option.IDos1Active": "i-Dos 1",
    "LaundryCare.Washer.Option.IDos2Active": "i-Dos 2",
    "LaundryCare.Washer.Setting.IDos1BaseLevel": "i-Dos 1 base level",
    "LaundryCare.Washer.Setting.IDos2BaseLevel": "i-Dos 2 base level",
    "LaundryCare.Washer.Option.VarioPerfect": "VarioPerfect",
    "LaundryCare.WasherDryer.Option.VarioPerfect": "VarioPerfect",
}


def _words(segment: str) -> list[str]:
    """One segment of a key broken into the words it was written from."""
    return [
        PADDED.sub("", word) if word.isdigit() else word
        for word in CAMEL.split(segment)
        if word
    ]


def _sentence(words: list[str]) -> str:
    """Words joined the way Home Assistant writes a name.

    The first word starts with a capital and the rest do not, except that a
    word written all in capitals is an abbreviation and keeps them.
    """
    written = []
    for word in words:
        respelt = SPELLINGS.get(word.lower())
        if respelt is not None:
            word = respelt
        elif word.isupper() and len(word) > 1:
            written.append(word)
            continue
        written.append(word.lower())
    if not written:
        return ""
    first = written[0]
    return " ".join([first[:1].upper() + first[1:], *written[1:]])


def _tail(key: str) -> str:
    """What is left of a key once the family and the part are taken off."""
    found = KIND.search(key)
    return key[found.end() :] if found else key.rsplit(".", 1)[-1]


def readable(key: str) -> str:
    """What to call the field this key names."""
    named = NAMES.get(key)
    if named is not None:
        return named
    words: list[str] = []
    for segment in _tail(key).split("."):
        words += _words(segment)
    return _sentence(words) or key


def label(key: str) -> str:
    """What to call the value this key names.

    A value is shown in a list of its siblings, which already say what they
    are between them, so only the last part of the key is worth reading out.
    """
    named = NAMES.get(key)
    if named is not None:
        return named
    return _sentence(_words(key.rsplit(".", 1)[-1])) or key


def distinct(keys: list[str], labels: dict[str, str]) -> dict[str, str]:
    """Labels that tell their keys apart, lengthening only the ones that clash.

    An oven names two of its dishes the same way under different cooking
    methods, and a list offering the same word twice is a list where one of
    them cannot be chosen. Only the keys that collide are given more of their
    own path, so a well behaved appliance reads exactly as it would have.
    """
    shown: dict[str, list[str]] = {}
    for key in keys:
        shown.setdefault(labels[key], []).append(key)
    settled = {}
    for text, sharing in shown.items():
        if len(sharing) == 1:
            settled[sharing[0]] = text
            continue
        for key in sharing:
            parts = _tail(key).split(".")
            longer = _sentence(_words(parts[-2])) if len(parts) > 1 else ""
            settled[key] = f"{text} ({longer})" if longer else key
    return settled
