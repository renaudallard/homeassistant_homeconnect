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

"""Turning what an appliance says into what the rest of this expects.

The whole point of local control is that nothing above it can tell. So what
is checked here is that the shapes coming out match the shapes the cloud
half produces for the same appliance, key for key and value for value.
"""

from __future__ import annotations

from pathlib import Path

from custom_components.homeconnect import iddf, local
from custom_components.homeconnect.capability import (
    NUMBER,
    SELECT,
    SWITCH,
    platform_for,
)

FIXTURES = Path(__file__).parent / "fixtures"
ENTRIES = iddf.parse(
    (FIXTURES / "FeatureMapping.xml").read_bytes(),
    (FIXTURES / "DeviceDescription.xml").read_bytes(),
)
DESCRIBED = local.describe(ENTRIES)


def test_a_setting_becomes_what_it_would_have_from_the_cloud() -> None:
    """The same rules decide, so a choice of three is a choice either way
    round and a flag is a switch either way round."""
    power = DESCRIBED.settings["BSH.Common.Setting.PowerState"]
    assert platform_for(power) is SELECT
    assert platform_for(DESCRIBED.settings["BSH.Common.Setting.ChildLock"]) is SWITCH


def test_a_choice_between_on_and_off_is_a_switch_here_too() -> None:
    entries = dict(ENTRIES)
    entries[0x0100] = iddf.Entry(
        uid=0x0100,
        kind="setting",
        key="BSH.Common.Setting.PowerState",
        access="readWrite",
        values={
            1: "BSH.Common.EnumType.PowerState.Off",
            2: "BSH.Common.EnumType.PowerState.On",
        },
    )
    power = local.describe(entries).settings["BSH.Common.Setting.PowerState"]
    assert platform_for(power) is SWITCH
    assert power.on_value() == "BSH.Common.EnumType.PowerState.On"
    assert power.off_value() == "BSH.Common.EnumType.PowerState.Off"


def test_the_commands_are_kept_apart_from_the_settings() -> None:
    assert DESCRIBED.commands == ("BSH.Common.Command.AcknowledgeEvent",)
    assert "BSH.Common.Command.AcknowledgeEvent" not in DESCRIBED.settings


def test_what_it_is_holding_is_sorted_the_way_the_cloud_sorts_it() -> None:
    found = local.sort(ENTRIES, {0x0100: 2, 0x0101: 5, 0x0102: True, 0x0103: 7})
    assert found.settings["BSH.Common.Setting.PowerState"].value == (
        "BSH.Common.EnumType.PowerState.On"
    )
    assert found.status["BSH.Common.Status.OperationState"].value == (
        "BSH.Common.EnumType.OperationState.Run"
    )
    assert found.settings["BSH.Common.Setting.ChildLock"].value is True
    assert found.status["Cooking.Hob.Status.Zone.001.PowerLevel"].value == 7
    assert not found.events


def test_an_event_lands_among_the_events() -> None:
    found = local.sort(ENTRIES, {0x0105: True})
    assert found.events["BSH.Common.Event.ProgramFinished"].value is True


def test_a_number_it_never_described_is_dropped() -> None:
    """There is nothing to call it and nothing to say what its value means."""
    found = local.sort(ENTRIES, {0x0100: 2, 0xDEAD: 1})
    assert list(found.settings) == ["BSH.Common.Setting.PowerState"]


def _with_programmes() -> dict[int, iddf.Entry]:
    entries = dict(ENTRIES)
    entries[0x0300] = iddf.Entry(0x0300, "program", "LaundryCare.Washer.Program.Cotton")
    entries[0x0301] = iddf.Entry(0x0301, "program", "LaundryCare.Washer.Program.Wool")
    entries[0x0302] = iddf.Entry(
        0x0302,
        "option",
        "LaundryCare.Washer.Option.Temperature",
        access="readWrite",
        minimum=20,
        maximum=90,
        under=0x0300,
    )
    entries[0x0303] = iddf.Entry(
        0x0303,
        "option",
        "BSH.Common.Option.Duration",
        access="readWrite",
        minimum=0,
        maximum=3600,
    )
    entries[0x0304] = iddf.Entry(
        0x0304, "setting", "BSH.Common.Root.SelectedProgram", access="readWrite"
    )
    entries[0x0305] = iddf.Entry(0x0305, "status", "BSH.Common.Root.ActiveProgram")
    return entries


def test_an_option_written_inside_a_programme_belongs_to_it() -> None:
    """And one written on its own belongs to all of them, which is how a
    description that does not bother to say says it."""
    described = local.describe(_with_programmes())
    assert set(described.programs) == {
        "LaundryCare.Washer.Program.Cotton",
        "LaundryCare.Washer.Program.Wool",
    }
    cotton = described.options["LaundryCare.Washer.Program.Cotton"]
    wool = described.options["LaundryCare.Washer.Program.Wool"]
    assert "LaundryCare.Washer.Option.Temperature" in cotton
    assert "LaundryCare.Washer.Option.Temperature" not in wool
    # The one with no programme of its own turns up under both.
    assert "BSH.Common.Option.Duration" in cotton
    assert "BSH.Common.Option.Duration" in wool
    assert platform_for(cotton["LaundryCare.Washer.Option.Temperature"]) is NUMBER


def test_the_programme_slots_hold_a_programme_rather_than_a_value() -> None:
    entries = _with_programmes()
    found = local.sort(entries, {0x0304: 0x0300, 0x0305: 0x0301})
    assert found.selected == "LaundryCare.Washer.Program.Cotton"
    assert found.active == "LaundryCare.Washer.Program.Wool"
    # And they are not left lying among the settings as raw numbers.
    assert "BSH.Common.Root.SelectedProgram" not in found.settings


def test_nothing_running_is_said_by_the_slot_holding_nothing() -> None:
    found = local.sort(_with_programmes(), {0x0305: 0})
    assert found.active is None


def test_a_value_goes_back_as_the_number_it_goes_by() -> None:
    entry = ENTRIES[0x0100]
    assert local._as_sent(entry, "BSH.Common.EnumType.PowerState.On") == 2
    # A flag is a flag, and a figure is a figure.
    assert local._as_sent(ENTRIES[0x0102], True) is True
    assert local._as_sent(ENTRIES[0x0103], 7) == 7


def test_what_is_needed_to_talk_to_one_survives_being_written_down() -> None:
    known = local.Known(key="a-key", iv=None, entries=ENTRIES)
    read = local.Known.from_stored(known.as_stored())
    assert read is not None
    assert read.key == "a-key"
    assert read.entries[0x0100].key == ENTRIES[0x0100].key
    assert read.entries[0x0100].values == ENTRIES[0x0100].values
    assert local.describe(read.entries).settings.keys() == DESCRIBED.settings.keys()


def test_something_written_down_that_no_longer_reads_is_dropped() -> None:
    assert local.Known.from_stored({"key": "a", "entries": "not a mapping"}) is None
    assert local.Known.from_stored("nonsense") is None


def test_the_two_services_may_spell_an_appliance_differently() -> None:
    """One writes the brand, the model and the serial run together where the
    other writes the serial alone, and the join has to survive that."""
    keys = {"SIEMENS-EX651HEC1E-335030393548000200": {"key": "k"}}
    assert local._matching(keys, "335030393548000200") == {"key": "k"}
    assert local._matching(keys, "SIEMENS-EX651HEC1E-335030393548000200") == {
        "key": "k"
    }
    assert local._matching(
        {"335030393548000200": {"key": "k"}}, "SIEMENS-X-335030393548000200"
    ) == {"key": "k"}


def test_an_appliance_the_account_has_no_key_for_matches_nothing() -> None:
    keys = {"SIEMENS-EX651HEC1E-111111111111": {"key": "k"}}
    assert local._matching(keys, "999999999999") is None
    assert local._matching({}, "anything") is None
    assert local._matching(keys, "") is None
