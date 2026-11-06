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

"""What an account keeps between restarts.

Two stores, both by entry: what each model of appliance can do, as the cloud
or local control described it, and what local control needs to reach each
appliance directly. Neither is worth migrating, so anything written under
another version is thrown away and asked for again.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

# Bump when what is kept between restarts would no longer be understood.
# Anything written under another version is thrown away rather than migrated,
# so the next start reads it again instead of trusting it.
# Bumped whenever the description parser starts keeping something it did not
# before, so a description written by an older one is thrown away and asked
# for again rather than used half-read. 2: the two programme slots (0.0.18)
# and what each thing is (0.0.19), neither of which an older store holds.
# 4: each programme's own limits on its options, which an older store read
# past and so kept only the widest.
STORE_VERSION = 4


class ModelStore(Store[dict[str, Any]]):
    """What each model of appliance can do, kept between starts.

    Nothing in here is worth migrating. Anything written under a version that
    read it differently is thrown away and asked for again, which costs a
    handful of calls once and is the whole point of the version above.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep nothing, so that everything is read afresh."""
        return {}


def model_store(hass: HomeAssistant, entry: ConfigEntry) -> ModelStore:
    """Where an account's model descriptions are kept between starts."""
    return ModelStore(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.models")


def local_store(hass: HomeAssistant, entry: ConfigEntry) -> ModelStore:
    """Where what an appliance needs to be talked to directly is kept.

    Its key, which never changes, and its own description of itself, which
    changes only when the appliance's software does. Both cost a call to the
    account and neither is worth asking for twice.
    """
    return ModelStore(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.local")
