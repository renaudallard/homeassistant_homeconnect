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

"""Reading an appliance's own description of itself."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from custom_components.homeconnect import iddf
from custom_components.homeconnect.errors import HomeConnectError

FIXTURES = Path(__file__).parent / "fixtures"
MAPPING = (FIXTURES / "FeatureMapping.xml").read_bytes()
DESCRIPTION = (FIXTURES / "DeviceDescription.xml").read_bytes()
ENTRIES = iddf.parse(MAPPING, DESCRIPTION)


def test_every_numbered_thing_gets_the_key_it_stands_for() -> None:
    assert ENTRIES[0x0100].key == "BSH.Common.Setting.PowerState"
    assert ENTRIES[0x0101].key == "BSH.Common.Status.OperationState"
    assert ENTRIES[0x0105].key == "BSH.Common.Event.ProgramFinished"


def test_what_kind_of_thing_it_is_comes_from_how_it_is_listed() -> None:
    kinds = {ENTRIES[uid].kind for uid in ENTRIES}
    assert kinds == {"status", "setting", "command", "event"}
    assert ENTRIES[0x0100].kind == "setting"
    assert ENTRIES[0x0104].kind == "command"


def test_a_value_is_spelled_the_way_it_is_spelled_everywhere_else() -> None:
    """A member is written as its own last word under an enumeration holding
    the rest of the key. Put back together, it matches what the cloud sends
    for the same value, so nothing above has to know which way it came."""
    assert iddf.named_value(ENTRIES[0x0100], 2) == "BSH.Common.EnumType.PowerState.On"
    assert (
        iddf.named_value(ENTRIES[0x0101], 5) == "BSH.Common.EnumType.OperationState.Run"
    )


def test_a_figure_stays_a_figure() -> None:
    assert iddf.named_value(ENTRIES[0x0103], 4) == 4
    assert iddf.named_value(ENTRIES[0x0102], True) is True


def test_a_value_the_enumeration_does_not_list_is_left_as_it_came() -> None:
    """Better an unfamiliar number than a name it does not have."""
    assert iddf.named_value(ENTRIES[0x0100], 99) == 99


def test_what_it_will_take_is_read_off_the_description() -> None:
    assert ENTRIES[0x0100].writable
    assert not ENTRIES[0x0101].writable
    assert ENTRIES[0x0101].readable
    assert (ENTRIES[0x0103].minimum, ENTRIES[0x0103].maximum) == (0.0, 9.0)
    assert ENTRIES[0x0103].step == 1.0


def test_the_way_back_is_by_key() -> None:
    assert iddf.uids_by_key(ENTRIES)["BSH.Common.Setting.ChildLock"] == 0x0102


def test_nothing_is_read_by_where_it_sits() -> None:
    """A file that gains a section, or lists one in another order, still
    reads: what matters is the attribute each element carries."""
    shuffled = DESCRIPTION.replace(b"<commandList>", b"<somethingNew/><commandList>")
    entries = iddf.parse(MAPPING, shuffled)
    assert entries.keys() == ENTRIES.keys()


def test_a_number_nobody_named_is_left_out() -> None:
    """There is nothing to call it, so there is nothing to make of it."""
    extra = DESCRIPTION.replace(
        b"</statusList>", b'<status uid="0x0999" access="read"/></statusList>'
    )
    assert 0x0999 not in iddf.parse(MAPPING, extra)


def test_a_description_that_does_not_read_says_so() -> None:
    with pytest.raises(HomeConnectError, match="does not read"):
        iddf.parse(b"<not xml", DESCRIPTION)
    with pytest.raises(HomeConnectError, match="named nothing"):
        iddf.parse(MAPPING, b"<device/>")


def _archive(**members: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, body in members.items():
            bundle.writestr(name.replace("__", "-"), body)
    return buffer.getvalue()


def test_the_archive_is_opened_by_what_the_members_are_called() -> None:
    archive = _archive(
        **{
            "SIEMENS__EX651HEC1E_FeatureMapping.xml": MAPPING,
            "SIEMENS__EX651HEC1E_DeviceDescription.xml": DESCRIPTION,
        }
    )
    assert iddf.unpack(archive).keys() == ENTRIES.keys()


def test_an_archive_missing_a_half_says_which() -> None:
    archive = _archive(**{"only_FeatureMapping.xml": MAPPING})
    with pytest.raises(HomeConnectError, match="the two files"):
        iddf.unpack(archive)


def test_something_that_is_not_an_archive_says_so() -> None:
    with pytest.raises(HomeConnectError, match="not an archive"):
        iddf.unpack(b"not a zip at all")
