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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HomeConnectApi
from .auth import Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .coordinator import HomeConnectCoordinator
from .events import HomeConnectStream

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
    stream: HomeConnectStream


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
    # The first refresh reads what every appliance is and what it is doing,
    # and proves the stored tokens still work while it is at it.
    await coordinator.async_config_entry_first_refresh()

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
    # A platform that fails to set up leaves the entry unloaded, and Home
    # Assistant runs these before it gives up, so a connection to the cloud
    # cannot outlive the entry that opened it.
    entry.async_on_unload(stream.stop)
    entry.async_on_unload(coordinator.stop_settling)

    entry.runtime_data = HomeConnectData(
        api=api, coordinator=coordinator, stream=stream
    )
    _forget_what_is_gone(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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


async def async_unload_entry(
    hass: HomeAssistant, entry: HomeConnectConfigEntry
) -> bool:
    """Unload an account."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
