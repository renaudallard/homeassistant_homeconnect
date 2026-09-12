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
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import _forget_what_moved, local
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

    assert made.minor_version == 3
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


async def test_the_wifi_reading_is_switched_off_once_on_an_older_local_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A local entry set up before the reading was known to be useless has
    it switched off here, once, and a cloud entry is left with its real one."""
    from custom_components.homeconnect.const import CONF_TRANSPORT, LOCAL

    made = entry(hass, minor_version=2)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: LOCAL}
    )
    registry = er.async_get(hass)
    wifi = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{HAID}-BSH.Common.Status.WiFiSignalStrength",
        config_entry=made,
        suggested_object_id="washer_wi_fi_signal_strength_old",
    )
    assert wifi.disabled_by is None

    serve(aioclient_mock, [fixture("washer")])
    with (
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.keys",
            AsyncMock(return_value={HAID: {"key": "a-key"}}),
        ),
        patch(
            "custom_components.homeconnect.api.HomeConnectAccount.description",
            AsyncMock(return_value=b"a zip"),
        ),
        patch.object(local.Finder, "start", AsyncMock()),
        patch.object(local.Finder, "stop", AsyncMock()),
    ):
        await hass.config_entries.async_setup(made.entry_id)
        await hass.async_block_till_done()

    assert made.minor_version == 3
    after = registry.async_get(wifi.entity_id)
    assert after is not None
    assert after.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_the_cards_are_served_once(hass: HomeAssistant) -> None:
    """Every card ships with the integration and is served from it, so there
    is no file to host by hand, and only once however many accounts are set
    up."""
    from unittest.mock import AsyncMock

    from custom_components.homeconnect import cards

    hass.data.pop("lovelace", None)
    hass.http = AsyncMock()
    await cards.register(hass, "1.2.3")
    await cards.register(hass, "1.2.3")

    hass.http.async_register_static_paths.assert_awaited_once()
    (paths,) = hass.http.async_register_static_paths.await_args.args
    # Both cards, each with the caching resource so the module goes out as
    # text/javascript rather than a type the browser will not load.
    served = {path.url_path: path.cache_headers for path in paths}
    assert served == {
        "/homeconnect/homeconnect-hob-card.js": True,
        "/homeconnect/homeconnect-dishwasher-card.js": True,
        "/homeconnect/homeconnect-appliance-card.js": True,
        "/homeconnect/homeconnect-cooling-card.js": True,
    }


class _Resources:
    """A stand-in for the dashboard's own resource list."""

    def __init__(self) -> None:
        self.loaded = True
        self.items: list[dict[str, str]] = []
        self.created: list[dict[str, str]] = []
        self.updated: list[tuple[str, dict[str, str]]] = []

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict[str, str]]:
        return list(self.items)

    async def async_create_item(self, data: dict[str, str]) -> dict[str, str]:
        item = {"id": f"id{len(self.items)}", **data}
        self.items.append(item)
        self.created.append(data)
        return item

    async def async_update_item(self, item_id: str, changes: dict[str, str]) -> None:
        self.updated.append((item_id, changes))
        for item in self.items:
            if item["id"] == item_id:
                item.update(changes)


async def test_a_card_is_added_then_freshened_in_place() -> None:
    """A card missing from the dashboard is added as a module; one already
    there is moved to the running version rather than added a second time, so
    the list does not fill with a card's every past self."""
    from custom_components.homeconnect import cards

    url = "/homeconnect/homeconnect-hob-card.js"
    resources = _Resources()

    await cards._one(resources, url, "1.0.0")
    assert resources.created == [{"res_type": "module", "url": f"{url}?v=1.0.0"}]

    # The same version again touches nothing.
    await cards._one(resources, url, "1.0.0")
    assert len(resources.created) == 1
    assert resources.updated == []

    # A new version freshens the one entry in place.
    await cards._one(resources, url, "1.1.0")
    assert len(resources.created) == 1
    assert resources.updated == [("id0", {"url": f"{url}?v=1.1.0"})]


async def test_registering_cards_without_a_dashboard_is_harmless(
    hass: HomeAssistant,
) -> None:
    """A system with no storage-backed dashboard has nothing to register the
    cards with, which is stepped over rather than raised."""
    from custom_components.homeconnect import cards

    hass.data.pop("lovelace", None)
    await cards._add_resources(hass, "1.0.0")


async def test_the_cards_wait_for_the_start_when_asked_early(
    hass: HomeAssistant,
) -> None:
    """Asked before the start has finished, the resource registration waits
    for it rather than writing to a list that is not loaded yet."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    from custom_components.homeconnect import cards

    hass.data.pop("lovelace", None)
    hass.http = AsyncMock()
    hass.set_state(CoreState.not_running)
    try:
        await cards.register(hass, "1.2.3")
        # Served at once, but the dashboard is touched only after the start.
        hass.http.async_register_static_paths.assert_awaited_once()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
    finally:
        hass.set_state(CoreState.running)


async def test_the_cards_are_registered_with_a_storage_dashboard(
    hass: HomeAssistant,
) -> None:
    """A storage dashboard keeps a resource list; every card is added to it,
    and anything unrelated already there is stepped over."""
    from types import SimpleNamespace

    from custom_components.homeconnect import cards

    resources = _Resources()
    resources.items.append({"id": "other", "url": "/local/unrelated.js"})
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    await cards._add_resources(hass, "1.0.0")
    urls = {item["url"] for item in resources.items}
    assert "/local/unrelated.js" in urls
    assert "/homeconnect/homeconnect-hob-card.js?v=1.0.0" in urls
    assert len(resources.created) == len(cards.CARDS)


async def test_cards_on_a_yaml_dashboard_are_left_to_their_owner(
    hass: HomeAssistant,
) -> None:
    """A YAML dashboard's resources have no list to write to; that is noted
    and stepped over rather than raised."""
    from types import SimpleNamespace

    from custom_components.homeconnect import cards

    hass.data["lovelace"] = SimpleNamespace(resources=object())
    await cards._add_resources(hass, "1.0.0")


async def test_an_unloaded_resource_list_is_loaded_before_writing(
    hass: HomeAssistant,
) -> None:
    """A list not yet read from disk is loaded first, so writing the cards
    does not lose every other resource."""
    from types import SimpleNamespace

    from custom_components.homeconnect import cards

    resources = _Resources()
    resources.loaded = False
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    await cards._add_resources(hass, "1.0.0")
    assert resources.loaded is True
    assert len(resources.created) == len(cards.CARDS)


async def test_a_dashboard_that_errors_is_logged_not_raised(
    hass: HomeAssistant,
) -> None:
    """Anything unexpected from the resource list is logged and stepped over,
    not allowed to take the setup down with it."""
    from types import SimpleNamespace

    from custom_components.homeconnect import cards

    class Boom:
        loaded = True

        def async_items(self) -> list[dict[str, str]]:
            raise RuntimeError("the list would not read")

    hass.data["lovelace"] = SimpleNamespace(resources=Boom())
    await cards._add_resources(hass, "1.0.0")
