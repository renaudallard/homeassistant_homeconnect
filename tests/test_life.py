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

"""Setting up, going quiet, coming back, and being taken away."""

from __future__ import annotations

import copy
from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import _forget_what_moved
from custom_components.homeconnect.const import DOMAIN
from custom_components.homeconnect.coordinator import (
    SCAN_INTERVAL,
    SCAN_INTERVAL_STREAMING,
    SETTLE,
)
from custom_components.homeconnect.events import Event

from .common import API, device_for, entry, fixture, serve, set_up, state_of

HAID = "BOSCH-WAV28MH0GB-1234567890AB"


async def test_an_account_sets_up_and_unloads(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = await set_up(hass, aioclient_mock, "washer")
    assert made.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(made.entry_id)
    await hass.async_block_till_done()
    (afterwards,) = hass.config_entries.async_entries(DOMAIN)
    assert afterwards.state is ConfigEntryState.NOT_LOADED


async def test_an_appliance_that_is_off_at_the_wall_still_has_a_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """It answers the listing and nothing else, which is not the same as
    having stopped having settings."""
    offline = copy.deepcopy(fixture("washer"))
    offline["appliance"]["connected"] = False
    serve(aioclient_mock, [offline])
    made = entry(hass)
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert device_for(hass, made, HAID) is not None
    assert state_of(hass, "binary_sensor.washer_connection") == "off"


async def test_nothing_is_learnt_from_an_appliance_that_is_not_answering(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An empty description would otherwise be kept and believed for good."""
    offline = copy.deepcopy(fixture("washer"))
    offline["appliance"]["connected"] = False
    serve(aioclient_mock, [offline])
    made = entry(hass)
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    coordinator = made.runtime_data.coordinator
    assert coordinator.data[HAID].model.settings == {}
    assert not coordinator.data[HAID].model.described


async def test_what_a_model_can_do_is_read_once_and_kept(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reading it costs a call for every setting, and the answer never moves."""
    made = await set_up(hass, aioclient_mock, "washer")
    stored = await made.runtime_data.coordinator._store.async_load()
    assert stored is not None
    described = stored["WAV28MH0GB/01"]
    assert described["described"] is True
    assert "BSH.Common.Setting.ChildLock" in described["settings"]
    # What it happened to be holding is not worth remembering until next time.
    assert "value" not in described["settings"]["BSH.Common.Setting.ChildLock"]


async def test_a_kept_description_reads_back_as_what_it_described(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = await set_up(hass, aioclient_mock, "washer")
    coordinator = made.runtime_data.coordinator
    written = coordinator.data[HAID].model.as_stored()

    from custom_components.homeconnect.coordinator import Model

    read = Model.from_stored(written)
    assert read is not None
    power = read.settings["BSH.Common.Setting.PowerState"]
    # A list written down comes back as the tuple a description is made of.
    assert isinstance(power.values, tuple)
    assert power.switchable
    assert read.commands == coordinator.data[HAID].model.commands


async def test_a_description_that_no_longer_reads_is_thrown_away(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    from custom_components.homeconnect.coordinator import Model

    assert Model.from_stored({"settings": "not a mapping"}) is None
    assert Model.from_stored("nonsense") is None
    assert Model.from_stored({"settings": {}, "commands": []}) is None


async def test_the_poll_eases_off_once_the_cloud_is_pushing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = await set_up(hass, aioclient_mock, "washer")
    coordinator = made.runtime_data.coordinator
    assert coordinator.update_interval == SCAN_INTERVAL

    coordinator.set_streaming(True)
    assert coordinator.update_interval == SCAN_INTERVAL_STREAMING

    coordinator.set_streaming(False)
    await hass.async_block_till_done()
    assert coordinator.update_interval == SCAN_INTERVAL


async def test_an_appliance_taken_off_the_account_loses_its_device(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = await set_up(hass, aioclient_mock, "washer")
    assert device_for(hass, made, HAID) is not None

    await hass.config_entries.async_unload(made.entry_id)
    await hass.async_block_till_done()
    aioclient_mock.clear_requests()
    serve(aioclient_mock, [fixture("oven")])
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert device_for(hass, made, HAID) is None


async def test_dangerous_commands_are_switched_off_once_on_an_older_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """New entries never switch these on. One set up before they were tamed
    has them switched off here, the first time and once: a factory reset and
    the like should not be left a press away by an upgrade, and an ordinary
    command a user turned on is left alone."""
    made = entry(hass, minor_version=1)
    registry = er.async_get(hass)
    reset = registry.async_get_or_create(
        "button",
        DOMAIN,
        f"{HAID}-BSH.Common.Command.ApplyFactoryReset",
        config_entry=made,
        suggested_object_id="washer_apply_factory_reset",
    )
    pause = registry.async_get_or_create(
        "button",
        DOMAIN,
        f"{HAID}-BSH.Common.Command.PauseProgram",
        config_entry=made,
        suggested_object_id="washer_pause_old",
    )
    assert reset.disabled_by is None and pause.disabled_by is None

    serve(aioclient_mock, [fixture("washer")])
    with patch("custom_components.homeconnect.HomeConnectStream.start"):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    assert made.minor_version == 2
    # The dangerous one is switched off, the ordinary one left as it was.
    reset_now = registry.async_get(reset.entity_id)
    pause_now = registry.async_get(pause.entity_id)
    assert reset_now is not None and pause_now is not None
    assert reset_now.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert pause_now.disabled_by is None


async def test_a_key_that_moved_platform_loses_the_entity_it_was(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reading a description better moves some keys to another platform. The
    entity made under the old reading would otherwise sit in the registry for
    good, unavailable and beyond reach, beside the one that replaced it."""
    made = await set_up(hass, aioclient_mock, "washer")
    registry = er.async_get(hass)
    live = registry.async_get("switch.washer_child_lock")
    assert live is not None

    # One left behind by an older release, under the same key.
    left = registry.async_get_or_create(
        "number",
        DOMAIN,
        live.unique_id,
        config_entry=made,
        suggested_object_id="washer_child_lock_old",
    )
    assert registry.async_get(left.entity_id) is not None

    await hass.config_entries.async_unload(made.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(left.entity_id) is None
    # And the one that belongs there is untouched.
    assert registry.async_get("switch.washer_child_lock") is not None


async def test_a_lamp_keeps_its_light(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A lamp is several keys gathered into one light, and the light is filed
    under the key that switches it on. What that key would have become on its
    own says nothing about it, so taking the difference as a move would throw
    the light away on every restart."""
    made = await set_up(hass, aioclient_mock, "oven")
    registry = er.async_get(hass)
    lamp = registry.async_get("light.oven_light")
    assert lamp is not None
    assert lamp.unique_id.endswith("Cooking.Common.Setting.Lighting")

    # Run the tidying itself rather than a reload. A reload would make the
    # light again the moment after taking it away, which is not the same as
    # never having taken it away: the name, the area and the history hang off
    # that registration.
    _forget_what_moved(hass, made, made.runtime_data.coordinator)
    await hass.async_block_till_done()

    again = registry.async_get("light.oven_light")
    assert again is not None
    assert again.id == lamp.id


async def test_an_entity_of_a_key_nobody_describes_is_left_alone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Taking an entity away throws its history away with it, so only a key
    the appliance still describes, and describes one way, is considered."""
    made = await set_up(hass, aioclient_mock, "washer")
    registry = er.async_get(hass)
    kept = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{HAID}-Some.Key.Nobody.Describes",
        config_entry=made,
        suggested_object_id="washer_a_stranger",
    )
    # The readings and the one-off entities are not keys at all.
    connection = registry.async_get("binary_sensor.washer_connection")
    assert connection is not None

    await hass.config_entries.async_unload(made.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(kept.entity_id) is not None
    assert registry.async_get("binary_sensor.washer_connection") is not None


async def test_an_appliance_that_refuses_a_question_is_not_a_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An appliance that is off refuses to say what it will run, because that
    depends on a state it is not in. That is an answer, not an error."""
    # Registered first, because the first answer that matches is the one given.
    aioclient_mock.get(
        f"{API}/homeappliances/{HAID}/programs/available",
        status=409,
        json={"error": {"key": "SDK.Error.WrongOperationState", "description": "off"}},
    )
    serve(aioclient_mock, [fixture("washer")])
    made = entry(hass)
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert made.state is ConfigEntryState.LOADED
    assert state_of(hass, "sensor.washer_operation_state") == "Ready"
    assert made.runtime_data.coordinator.data[HAID].programs == ()


async def test_one_appliance_that_will_not_answer_is_one_appliance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Taking the account away over it would take the rest of the house too."""
    aioclient_mock.get(f"{API}/homeappliances/{HAID}/status", status=500, json={})
    serve(aioclient_mock, [fixture("washer"), fixture("oven")])
    made = entry(hass)
    await hass.config_entries.async_setup(made.entry_id)
    await hass.async_block_till_done()

    assert made.state is ConfigEntryState.LOADED
    assert state_of(hass, "sensor.oven_operation_state") == "Inactive"
    assert HAID not in made.runtime_data.coordinator.data


async def test_an_appliance_that_was_off_is_described_when_it_answers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """What a model can do is asked once and kept, and an appliance switched
    off at the wall cannot be asked. It has to be asked the moment it comes
    back rather than whenever the next look round the account comes."""
    offline = copy.deepcopy(fixture("washer"))
    offline["appliance"]["connected"] = False
    serve(aioclient_mock, [offline])
    made = entry(hass)
    with patch("custom_components.homeconnect.HomeConnectStream.start"):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    coordinator = made.runtime_data.coordinator
    assert not coordinator.data[HAID].model.described
    assert hass.states.get("switch.washer_child_lock") is None

    coordinator.apply(Event("CONNECTED", HAID, {}))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=SETTLE + 1))
    await hass.async_block_till_done()

    assert coordinator.data[HAID].model.described
    assert state_of(hass, "switch.washer_child_lock") == "off"
    assert state_of(hass, "sensor.washer_operation_state") == "Ready"


def complaint(hass: HomeAssistant, haid: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"never_answered_{haid}")


async def test_an_appliance_that_never_answers_is_explained(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One entity saying disconnected and no explanation reads like the
    integration failing, when it is the appliance declining to talk."""
    offline = copy.deepcopy(fixture("washer"))
    offline["appliance"]["connected"] = False
    serve(aioclient_mock, [offline])
    made = entry(hass)
    with patch("custom_components.homeconnect.HomeConnectStream.start"):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    raised = complaint(hass, HAID)
    assert raised is not None
    assert raised.translation_key == "never_answered"
    assert raised.translation_placeholders == {"name": "Washer", "type": "Washer"}
    assert not raised.is_fixable


async def test_an_appliance_that_answers_is_not_complained_about(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await set_up(hass, aioclient_mock, "washer")
    assert complaint(hass, HAID) is None


async def test_the_complaint_is_taken_back_once_it_answers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    offline = copy.deepcopy(fixture("washer"))
    offline["appliance"]["connected"] = False
    serve(aioclient_mock, [offline])
    made = entry(hass)
    with patch("custom_components.homeconnect.HomeConnectStream.start"):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()
    assert complaint(hass, HAID) is not None

    made.runtime_data.coordinator.apply(Event("CONNECTED", HAID, {}))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=SETTLE + 1))
    await hass.async_block_till_done()

    assert complaint(hass, HAID) is None


async def test_a_machine_that_used_to_work_is_not_a_repair(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Switched off today is not something to fix, and saying so would put a
    notice up every time somebody turned an oven off at the wall."""
    made = await set_up(hass, aioclient_mock, "washer")
    coordinator = made.runtime_data.coordinator
    described = copy.deepcopy(fixture("washer"))
    described["appliance"]["connected"] = False
    aioclient_mock.clear_requests()
    serve(aioclient_mock, [described])
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not coordinator.data[HAID].connected
    assert complaint(hass, HAID) is None


async def test_the_hob_card_is_served_and_loaded_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The card ships with the integration and is put on the frontend, so
    there is no resource to add by hand, and only once however many accounts
    are set up."""
    from unittest.mock import AsyncMock, patch

    from custom_components.homeconnect import _register_card

    hass.http = AsyncMock()
    with patch("custom_components.homeconnect.frontend.add_extra_js_url") as added:
        await _register_card(hass)
        await _register_card(hass)

    hass.http.async_register_static_paths.assert_awaited_once()
    added.assert_called_once()
    url = added.call_args.args[1]
    assert "homeconnect-hob-card.js" in url
    # The version is on the url so a new release is not read from the cache.
    assert "?v=" in url
