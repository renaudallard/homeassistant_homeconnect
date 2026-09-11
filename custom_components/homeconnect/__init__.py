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

"""Home Connect appliance integration.

An entry owns one Home Connect account and the appliances on it. The token
pair lives in the entry rather than in memory, because renewing rotates the
refresh token and a pair that is not written back leaves the account
unreachable after a restart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HomeConnectAccount, HomeConnectApi
from .auth import Tokens
from .capability import GATHERED, platform_for
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_TRANSPORT,
    DOMAIN,
    LOCAL,
)
from .coordinator import HomeConnectCoordinator, local_store
from .errors import HomeConnectAuthError, HomeConnectError
from .events import HomeConnectStream
from .local import LocalControl

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class HomeConnectData:
    """What an entry needs while it is loaded."""

    api: HomeConnectApi
    coordinator: HomeConnectCoordinator
    stream: HomeConnectStream | None
    local: LocalControl | None


type HomeConnectConfigEntry = ConfigEntry[HomeConnectData]


async def async_setup_entry(hass: HomeAssistant, entry: HomeConnectConfigEntry) -> bool:
    """Set up a Home Connect account."""
    session = async_get_clientsession(hass)

    async def store(renewed: Tokens) -> None:
        """Write a renewed pair back to the entry."""
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: renewed.access_token,
                CONF_REFRESH_TOKEN: renewed.refresh_token,
                CONF_EXPIRES_AT: renewed.expires_at,
            },
        )

    api = HomeConnectApi(
        session,
        Tokens(
            access_token=entry.data[CONF_ACCESS_TOKEN],
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
            expires_at=entry.data[CONF_EXPIRES_AT],
        ),
        # The cloud translates what it calls a programme and the values of a
        # setting, and it does it into whatever Home Assistant is set to.
        language=hass.config.language,
        on_tokens=store,
    )

    coordinator = HomeConnectCoordinator(hass, entry, api)
    await coordinator.async_load_models()

    local: LocalControl | None = None
    if entry.data.get(CONF_TRANSPORT) == LOCAL:
        local = LocalControl(
            hass,
            session,
            HomeConnectAccount(api),
            local_store(hass, entry),
            coordinator.apply_locally,
            coordinator.set_talking,
        )
        await local.load()
        await _learn(api, local)
        coordinator.local = local

    # The first refresh reads what every appliance is and what it is doing,
    # and proves the stored tokens still work while it is at it.
    await coordinator.async_config_entry_first_refresh()

    stream: HomeConnectStream | None = None
    if local is None:
        # The stream is how the cloud pushes changes. An appliance talked to
        # directly pushes them down its own connection, so there is nothing
        # for a second one to carry.
        stream = HomeConnectStream(
            session,
            lambda: api.headers("text/event-stream"),
            api.seconds_until_renewal,
            coordinator.apply,
            coordinator.set_streaming,
        )
        stream.start(
            lambda listening: entry.async_create_background_task(
                hass, listening, "Home Connect event stream"
            )
        )
        entry.async_on_unload(stream.stop)
    else:
        await local.start(
            lambda talking: entry.async_create_background_task(
                hass, talking, "Home Connect appliance"
            )
        )
        entry.async_on_unload(local.stop)
    # A platform that fails to set up leaves the entry unloaded, and Home
    # Assistant runs these before it gives up, so nothing opened here can
    # outlive the entry that opened it.
    entry.async_on_unload(coordinator.stop_settling)

    entry.runtime_data = HomeConnectData(
        api=api, coordinator=coordinator, stream=stream, local=local
    )
    _forget_what_is_gone(hass, entry, coordinator)
    _forget_what_moved(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _learn(api: HomeConnectApi, local: LocalControl) -> None:
    """Ask the account for whatever local control still needs.

    The account is the only place an appliance's key and its own description
    of itself are kept, and both are wanted before anything can be read from
    the appliance directly. Neither changes, so this asks once and the answer
    survives restarts.
    """
    try:
        listed = await api.appliances()
    except HomeConnectAuthError as err:
        # The appliance API turning the token down is the token being spent.
        raise ConfigEntryAuthFailed(str(err)) from err
    except HomeConnectError as err:
        raise ConfigEntryNotReady(f"could not read the account: {err}") from err

    try:
        await local.learn(
            [str(one["haId"]) for one in listed if isinstance(one.get("haId"), str)]
        )
    except HomeConnectError as err:
        # The account's own service refusing is not the token being spent:
        # the appliance API took the same one a moment ago. Asking the user
        # to sign in again would send them round a loop that cannot help.
        raise ConfigEntryNotReady(
            f"could not read what the appliances need for local control: {err}. "
            "Reconfigure this entry to reach them through the cloud instead."
        ) from err


def _forget_what_is_gone(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: HomeConnectCoordinator
) -> None:
    """Take away the devices of appliances that are no longer on the account.

    An appliance that has been unpaired keeps its device, its entities and its
    history until something says otherwise, and nothing else ever will.
    """
    registry = dr.async_get(hass)
    present = set(coordinator.data)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        gone = [
            identifier
            for domain, identifier in device.identifiers
            if domain == DOMAIN and identifier not in present
        ]
        if gone:
            _LOGGER.debug("%s is no longer on the account", device.name)
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


def _forget_what_moved(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: HomeConnectCoordinator
) -> None:
    """Take away entities of a key that now belongs to a different platform.

    What an appliance says about a key decides whether it becomes a switch, a
    choice, a figure or a reading. Reading the description better moves some
    of them, and the entity made under the old reading stays in the registry
    for good, unavailable and beyond reach, beside the one that replaced it.

    Only a key the appliance still describes is considered, and only where the
    description gives one answer for it. Anything else is left alone: an
    entity taken away is a history thrown away, and that cannot be undone.
    """
    belongs: dict[str, set[str | None]] = {}
    for haid, appliance in coordinator.data.items():
        described = dict(appliance.model.settings)
        for options in appliance.model.options.values():
            described.update(options)
        for key, found in described.items():
            # A lamp is several keys gathered into one light, so what any of
            # them would have become on its own says nothing about it.
            if key in GATHERED:
                continue
            belongs.setdefault(f"{haid}-{key}", set()).add(platform_for(found))

    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        wanted = belongs.get(registered.unique_id)
        if wanted is None or len(wanted) != 1:
            continue
        settled = next(iter(wanted))
        if settled is not None and registered.domain != settled:
            _LOGGER.debug(
                "%s is a %s now, so the %s it was is taken away",
                registered.unique_id.split("-", 1)[-1],
                settled,
                registered.domain,
            )
            registry.async_remove(registered.entity_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: HomeConnectConfigEntry
) -> bool:
    """Unload an account."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
