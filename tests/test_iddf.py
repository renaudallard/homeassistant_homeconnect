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
    assert kinds == {
        "status",
        "setting",
        "command",
        "event",
        "program",
        "activeProgram",
        "selectedProgram",
    }
    assert ENTRIES[0x0100].kind == "setting"
    assert ENTRIES[0x0104].kind == "command"


def test_the_programme_slots_are_read_though_they_sit_in_no_list() -> None:
    """An appliance writes these two as their own kinds rather than as
    entries in a list, and they are where it says what it is running and
    what it is set to run. Read without them, a description of sixty
    programmes cannot say which of them is on."""
    active = ENTRIES[0x0107]
    assert active.key == "BSH.Common.Root.ActiveProgram"
    assert active.kind == "activeProgram"
    assert not active.writable
    selected = ENTRIES[0x0108]
    assert selected.key == "BSH.Common.Root.SelectedProgram"
    assert selected.writable


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


# A programme may restate an option it shares, narrowing the range it will
# take. It names the option by refUID, the number the root option carries as
# its uid, and carries no uid of its own.
NESTED_MAPPING = b"""<?xml version="1.0" encoding="UTF-8"?>
<featureMappingFile version="1.0">
  <featureDescriptionList>
    <feature refUID="0x0224">BSH.Common.Option.Duration</feature>
    <feature refUID="0x0301">Cooking.Hob.Program.Frying</feature>
    <feature refUID="0x0302">Cooking.Hob.Program.Simmer</feature>
  </featureDescriptionList>
</featureMappingFile>"""

NESTED_DESCRIPTION = b"""<?xml version="1.0" encoding="UTF-8"?>
<device version="1.0">
  <optionList>
    <option uid="0x0224" access="readWrite" available="true"
            refCID="10" refDID="82" min="0" max="266400"/>
  </optionList>
  <programList>
    <program uid="0x0301" available="true">
      <option refUID="0x0224" access="readWrite" available="true"
              min="0" max="35940"/>
    </program>
    <program uid="0x0302" available="true"/>
  </programList>
</device>"""


def test_a_programme_keeps_its_own_limits_on_an_option_it_refines() -> None:
    """An option written inside a programme with no uid of its own narrows
    the root option of the same name. It is kept apart from the root and from
    the other programmes' versions, under the programme it belongs to."""
    entries = iddf.parse(NESTED_MAPPING, NESTED_DESCRIPTION)
    made = (0x0301 << 16) | 0x0224
    refinement = entries[made]
    assert refinement.key == "BSH.Common.Option.Duration"
    assert refinement.under == 0x0301
    assert refinement.maximum == 35940
    # The narrowing does not restate what the thing is; that stays the root's.
    assert refinement.content is None
    # The root keeps the widest range and what it is, under no programme.
    assert entries[0x0224].maximum == 266400
    assert entries[0x0224].content == 0x10
    assert entries[0x0224].under is None
    # A programme that says nothing of the option gets no refinement of it.
    assert (0x0302 << 16) | 0x0224 not in entries
    # The way back to the appliance points at the root, not a made-up number.
    assert iddf.uids_by_key(entries)["BSH.Common.Option.Duration"] == 0x0224


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


def test_what_a_thing_is_comes_from_the_number_the_schema_publishes() -> None:
    """A description says how large a thing may be and never what it is. The
    number beside it is what says, against a table every description names by
    its address."""
    from custom_components.homeconnect.content import content

    assert ENTRIES[0x010A].content == 0x12
    assert content(ENTRIES[0x010A].content) == ("dbm", "Integer")
    assert content(ENTRIES[0x010B].content) == ("string", "String")
    assert content(ENTRIES[0x010C].content) == ("timeSpan", "Integer")
    # One written without a number is not one to guess at.
    assert ENTRIES[0x0100].content is None
    assert content(None) is None
