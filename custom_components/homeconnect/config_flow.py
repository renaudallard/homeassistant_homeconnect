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

"""Config flow for the Home Connect integration.

A Home Connect account is signed in to at SingleKey ID, in a browser, and
there is no way round that. The sign in page is behind a captcha and says so
in as many words to anything that tries without one: "please activate
JavaScript in order to progress". So the user signs in as they always would,
whatever that account takes, and hands back the address the browser ends on.

That address carries a one time code, worth nothing to anyone without the
secret generated before the first address was handed out, so it can travel
through a clipboard without any of it being worth guarding.

Where the browser ends is a page built to hand a phone the session, and it can
be handed the answer in either of two shapes: as a plain parameter, or with
the whole hand-off encoded into one argument. Both are read, along with a bare
code from somebody who picked it out themselves.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_CODE
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from . import auth
from .api import HomeConnectApi
from .auth import Tokens
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from .errors import HomeConnectAuthError, HomeConnectError

_LOGGER = logging.getLogger(__name__)

# What an appliance puts in the record it shouts on the network. Only the
# first three are worth reading: they are what turns "something Home Connect
# is on the network" into "a Siemens hob" on the discovery card.
TYPE = "type"
BRAND = "brand"
MODEL = "vib"

PASTED = vol.Schema(
    {
        vol.Required(CONF_CODE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)


class HomeConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through signing in to a Home Connect account."""

    VERSION = 1

    def __init__(self) -> None:
        # Made once per attempt and kept for as long as the flow is open. The
        # secret never leaves here until the code comes back, which is what
        # stops a code read out of somebody's address bar being worth
        # anything to them.
        self._verifier = auth.verifier()
        self._state = secrets.token_urlsafe(16)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in, and make an entry for the account that answers."""
        return await self._sign_in("user", user_input)

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """An appliance shouted on the network, so offer to sign in.

        Discovery says an appliance is there and what sort it is. It says
        nothing that would let anyone talk to it: the account is what
        authorises that, so this leads to the same sign in as any other way
        in, with the appliance named on the card to say what prompted it.

        One sign in covers every appliance on the account, so the second
        appliance to shout has nothing to add: not to an account already set
        up, and not to a card already waiting to be clicked either. A kitchen
        of them would otherwise put up a card each, all of them asking for the
        same sign in and all but one of them going stale the moment it is
        given.
        """
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        if self._async_in_progress(include_uninitialized=True):
            return self.async_abort(reason="already_in_progress")
        self.context["title_placeholders"] = {"name": _describe(discovery_info)}
        return await self.async_step_user()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Sign in again, the stored tokens having stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The same sign in, ending in the entry that is already there."""
        return await self._sign_in("reauth_confirm", user_input)

    async def _sign_in(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                tokens = await self._exchange(user_input[CONF_CODE])
            except HomeConnectAuthError as err:
                _LOGGER.warning("signing in failed: %s", err)
                errors["base"] = "invalid_auth"
            except HomeConnectError as err:
                _LOGGER.warning("could not reach the service: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("unexpected failure while signing in")
                errors["base"] = "unknown"
            else:
                return await self._finish(tokens)
        return self.async_show_form(
            step_id=step,
            data_schema=PASTED,
            errors=errors,
            description_placeholders={
                "url": auth.authorize_url(self._verifier, self._state)
            },
        )

    async def _exchange(self, answer: str) -> Tokens:
        """Take what the browser ended on and turn it into a token pair."""
        if not _ours(answer, self._state):
            raise HomeConnectAuthError("that address is from a different sign in")
        session = async_get_clientsession(self.hass)
        code = auth.code_from(answer)
        return await self._prove(await auth.exchange(session, code, self._verifier))

    async def _prove(self, tokens: Tokens) -> Tokens:
        """Use the pair once before writing it anywhere.

        A token the cloud will hand out and then refuse makes an entry that
        fails on every start with nothing to say about why.
        """
        session = async_get_clientsession(self.hass)
        await HomeConnectApi(session, tokens, self.hass.config.language).appliances()
        return tokens

    async def _finish(self, tokens: Tokens) -> ConfigFlowResult:
        """Make the entry, or hand the new tokens to the one already there."""
        data: dict[str, Any] = {
            CONF_ACCESS_TOKEN: tokens.access_token,
            CONF_REFRESH_TOKEN: tokens.refresh_token,
            CONF_EXPIRES_AT: tokens.expires_at,
        }
        if tokens.account is not None:
            await self.async_set_unique_id(tokens.account)
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            # Signing in as somebody else would leave the entry holding one
            # account's appliances and another account's tokens.
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(entry, data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Home Connect", data=data)


def _describe(found: ZeroconfServiceInfo) -> str:
    """What to call the appliance that prompted this.

    An appliance names itself in the record it shouts, as a brand, a type and
    the code on its rating plate. Anything it leaves out is left out here too
    rather than guessed at, and one that says nothing useful falls back to
    what the network calls it.
    """
    said = found.properties
    words = [str(said[key]) for key in (BRAND, TYPE, MODEL) if said.get(key)]
    return " ".join(words) if words else found.name.split(".")[0]


def _ours(answer: str, state: str) -> bool:
    """Whether this address came back from the sign in we started.

    The state travels out with the request and comes back untouched, so an
    address carrying somebody else's is one to have nothing to do with. An
    address carrying none at all is a bare code, which the user has picked out
    themselves and which has nowhere to carry one.
    """
    found = parse_qs(urlparse(answer.strip()).query).get("state")
    return not found or found[0] == state
