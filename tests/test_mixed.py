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

"""An account reached directly where it can be and through the cloud otherwise.

The washer has a key on the account and has been found on the network before;
the oven has no key. Set to mixed, the washer is talked to directly and the
oven through the cloud; set to local, the oven is the one appliance left out,
and only it says so.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import iddf, local
from custom_components.homeconnect.const import CONF_TRANSPORT, DOMAIN, LOCAL, MIXED
from custom_components.homeconnect.errors import HomeConnectConnectionError
from custom_components.homeconnect.events import Event
from custom_components.homeconnect.http import issue_id
from custom_components.homeconnect.store import STORE_VERSION

from .common import described_as, entry, fixture, serve, state_of

WASHER = "BOSCH-WAV28MH0GB-1234567890AB"
OVEN = "SIEMENS-HB678GBS6B-FEDCBA987654"
DOOR = "BSH.Common.Status.DoorState"


# Where the washer was found on the network.
SEEN = local.Where("192.0.2.4", 443)


class Quiet:
    """A link to an appliance that never answers, and never tries to."""

    talking = False

    def start(self, _spawn: Any) -> None:
        return None

    async def stop(self) -> None:
        return None


async def _set_up(
    hass: HomeAssistant,
    mock: AiohttpClientMocker,
    storage: dict[str, Any],
    transport: str,
    placed: bool = True,
) -> MockConfigEntry:
    serve(mock, [fixture("washer"), fixture("oven")])
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: transport}
    )
    if placed:
        # Learnt on an earlier start, and found on the network then.
        known = local.Known(
            key="AAAA",
            iv=None,
            entries=iddf.unpack(described_as(WASHER)),
            where=SEEN,
        )
        name = f"{DOMAIN}.{made.entry_id}.local"
        storage[name] = {
            "version": STORE_VERSION,
            "minor_version": 1,
            "key": name,
            "data": {WASHER: known.as_stored()},
        }
    with (
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.keys",
            AsyncMock(return_value={WASHER: {"key": "AAAA"}}),
        ),
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.description",
            AsyncMock(return_value=described_as(WASHER)),
        ),
        patch.object(local.Finder, "start", AsyncMock()),
        patch.object(local.Finder, "stop", AsyncMock()),
        patch.object(local.LocalControl, "_make", lambda *_a: Quiet()),
        patch("custom_components.homeconnect.HomeConnectStream.start"),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()
    return made


@pytest.fixture
async def mixed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> MockConfigEntry:
    return await _set_up(hass, aioclient_mock, hass_storage, MIXED)


async def test_each_appliance_says_which_way_it_is_reached(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    assert mixed.state is ConfigEntryState.LOADED
    assert state_of(hass, "sensor.washer_transport") == "local"
    assert state_of(hass, "sensor.oven_transport") == "cloud"
    # Read through the cloud, the oven has what the cloud says about it.
    assert state_of(hass, "sensor.oven_operation_state") != "unavailable"


async def test_an_appliance_reached_through_the_cloud_is_nothing_to_repair(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, issue_id("local_unreachable", OVEN)) is None


async def test_both_ways_run_side_by_side(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    assert mixed.runtime_data.local is not None
    assert mixed.runtime_data.stream is not None


async def test_a_change_goes_the_way_its_appliance_is_reached(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    coordinator = mixed.runtime_data.coordinator
    written = AsyncMock()
    sent = AsyncMock()
    with (
        patch.object(mixed.runtime_data.local, "write", written),
        patch.object(coordinator.api, "set_setting", sent),
    ):
        await coordinator.apply_setting(WASHER, "BSH.Common.Setting.ChildLock", True)
        await coordinator.apply_setting(OVEN, "BSH.Common.Setting.ChildLock", True)
    written.assert_awaited_once_with(WASHER, "BSH.Common.Setting.ChildLock", True)
    sent.assert_awaited_once_with(OVEN, "BSH.Common.Setting.ChildLock", True)


async def test_the_cloud_stream_only_speaks_for_the_cloud_appliances(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    """The washer's own connection says it first, and the cloud's later
    account would undo it."""
    coordinator = mixed.runtime_data.coordinator
    opened = {"key": DOOR, "value": "BSH.Common.EnumType.DoorState.Open"}
    for haid in (WASHER, OVEN):
        coordinator.apply(Event("STATUS", haid, {"items": [opened]}))
    assert DOOR not in coordinator.data[WASHER].status
    assert coordinator.data[OVEN].status[DOOR].value == opened["value"]


async def test_two_of_one_model_reached_both_ways_keep_their_own_description(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    """What was learnt for one reached directly is not what the cloud says
    about the same model, so neither overwrites the other."""
    coordinator = mixed.runtime_data.coordinator
    described = {"enumber": "SAME/01"}
    cloud = coordinator._model(OVEN, described, False)
    direct = coordinator._model(WASHER, described, True)
    assert cloud is not direct
    assert coordinator._model(OVEN, described, False) is cloud


async def test_set_to_local_the_appliance_without_a_key_is_the_only_one_affected(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    made = await _set_up(hass, aioclient_mock, hass_storage, LOCAL)
    assert made.state is ConfigEntryState.LOADED
    assert made.runtime_data.stream is None
    assert state_of(hass, "sensor.oven_transport") == "local"
    issues = ir.async_get(hass)
    assert (
        issues.async_get_issue(DOMAIN, issue_id("local_unreachable", OVEN)) is not None
    )
    assert issues.async_get_issue(DOMAIN, issue_id("local_unreachable", WASHER)) is None
    # Not also told to get it talking to the cloud, which it never would here.
    assert issues.async_get_issue(DOMAIN, issue_id("never_answered", OVEN)) is None
    assert made.runtime_data.local is not None
    assert made.runtime_data.local.knows(WASHER)


async def test_one_never_found_on_the_network_stays_on_the_cloud(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """A key says nothing about whether the appliance can be reached from
    here, and the cloud can reach it meanwhile."""
    await _set_up(hass, aioclient_mock, hass_storage, MIXED, placed=False)
    assert state_of(hass, "sensor.washer_transport") == "cloud"
    assert state_of(hass, "sensor.washer_operation_state") != "unavailable"


async def test_turning_up_on_the_network_takes_it_over(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Where it is gets written down before setting up again, or it would
    be on the cloud again afterwards and found again, over and over."""
    made = await _set_up(hass, aioclient_mock, hass_storage, MIXED, placed=False)
    control = made.runtime_data.local
    reloaded = []
    with (
        patch.object(
            control._finder, "where", lambda haid: SEEN if haid == WASHER else None
        ),
        patch.object(
            hass.config_entries,
            "async_schedule_reload",
            lambda entry_id: reloaded.append(entry_id),
        ),
    ):
        control._look_again()
        await hass.async_block_till_done()
        # Heard again before the reload, it is not announced twice.
        control._look_again()
        await hass.async_block_till_done()
    assert reloaded == [made.entry_id]
    stored = hass_storage[f"{DOMAIN}.{made.entry_id}.local"]["data"][WASHER]
    assert stored["host"] == SEEN.host
    # And until then the cloud still has it.
    assert state_of(hass, "sensor.washer_transport") == "cloud"


async def test_the_cloud_going_down_takes_only_its_appliances_with_it(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    """What a cloud appliance said last is not shown as current while the
    cloud cannot be read, and the entry does not fail over it."""
    coordinator = mixed.runtime_data.coordinator
    assert state_of(hass, "sensor.oven_operation_state") != "unavailable"
    down = AsyncMock(side_effect=HomeConnectConnectionError("unreachable"))
    with patch.object(coordinator.api, "appliances", down):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert state_of(hass, "sensor.oven_operation_state") == "unavailable"
    assert state_of(hass, "sensor.washer_transport") == "local"

    # Back up, it is back.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, "sensor.oven_operation_state") != "unavailable"


async def test_removing_the_account_takes_its_repairs_away(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    made = await _set_up(hass, aioclient_mock, hass_storage, LOCAL)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id("never_answered", WASHER),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="never_answered",
    )
    issues = ir.async_get(hass)
    assert (
        issues.async_get_issue(DOMAIN, issue_id("local_unreachable", OVEN)) is not None
    )

    await hass.config_entries.async_remove(made.entry_id)
    await hass.async_block_till_done()

    assert not [issue for domain, issue in issues.issues if domain == DOMAIN]


@pytest.mark.parametrize(("transport", "level"), [(LOCAL, "WARNING"), (MIXED, "INFO")])
async def test_an_appliance_without_a_key_is_only_a_warning_where_it_is_lost(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    transport: str,
    level: str,
) -> None:
    """Set to mixed, the oven being on the cloud is what was asked for, and
    a warning at every start would be a warning about nothing."""
    caplog.set_level(logging.DEBUG, logger="custom_components.homeconnect")
    await _set_up(hass, aioclient_mock, hass_storage, transport)
    said = [
        record.levelname
        for record in caplog.records
        if "is not reached directly" in record.getMessage()
    ]
    assert said == [level]
    # Learning itself says it only quietly, leaving how loudly to the setup.
    assert not [
        record
        for record in caplog.records
        if record.name.endswith(".local") and record.levelname == "WARNING"
    ]


async def test_the_report_says_which_way_each_appliance_is_reached(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    from custom_components.homeconnect.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    report = await async_get_config_entry_diagnostics(hass, mixed)
    reached = {one["type"]: one["reached"] for one in report["appliances"]}
    assert reached == {"Washer": "local", "Oven": "cloud"}


async def test_one_reached_directly_being_unpaired_is_still_heard(
    hass: HomeAssistant, mixed: MockConfigEntry
) -> None:
    """Its own connection cannot say it has been taken off the account, so
    that one the cloud's stream is listened to for."""
    coordinator = mixed.runtime_data.coordinator
    refreshed = AsyncMock()
    with patch.object(coordinator, "async_request_refresh", refreshed):
        coordinator.apply(Event("DEPAIRED", WASHER, {}))
        await hass.async_block_till_done()
    refreshed.assert_awaited_once()


async def test_what_local_mode_described_is_not_what_the_cloud_uses(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Before local descriptions had a key of their own, local mode kept
    them under the plain model number, and moving to the cloud took them as
    already asked. A store from then is dropped once, and asked again."""
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    name = f"{DOMAIN}.{made.entry_id}.models"
    hass_storage[name] = {
        "version": STORE_VERSION,
        "minor_version": 1,
        "key": name,
        "data": {
            "WAV28MH0GB/01": {
                "settings": {},
                "commands": ["BSH.Common.Command.AbortProgram"],
                "options": {},
                "described": True,
            }
        },
    }
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()
    model = made.runtime_data.coordinator.data[WASHER].model
    assert "BSH.Common.Command.PauseProgram" in model.commands
    assert "BSH.Common.Command.AbortProgram" not in model.commands


async def test_a_repair_does_not_name_the_appliance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Every repair goes into a diagnostics download as it is, id and all,
    and the appliance id is kept out of everything else there."""
    await _set_up(hass, aioclient_mock, hass_storage, LOCAL)
    ours = [issue for (domain, issue) in ir.async_get(hass).issues if domain == DOMAIN]
    assert ours
    for issue in ours:
        assert OVEN not in issue
        assert OVEN.split("-")[-1] not in issue


async def test_a_repair_filed_under_the_appliance_id_is_taken_away(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Older releases named their repairs after the appliance, and nothing
    files one under that name any more to clear it."""
    for kind in ("never_answered", "local_unreachable"):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{kind}_{OVEN}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=kind,
        )
    await _set_up(hass, aioclient_mock, hass_storage, MIXED)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"never_answered_{OVEN}") is None
    assert issues.async_get_issue(DOMAIN, f"local_unreachable_{OVEN}") is None
