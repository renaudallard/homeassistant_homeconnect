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

"""Being told to wait by the cloud.

The developer documentation counts every request against a daily quota, and
counts a run of refused ones against a second, shorter block. Once the cloud
has said how long to wait, nothing is sent before that is over.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.errors import HomeConnectTooManyRequests

from .test_account import api_for, session  # noqa: F401

LISTING = "https://api.home-connect.com/api/homeappliances"


def at(now: float) -> Any:
    """Stop the integration's clock at one moment, and only its clock."""
    return patch(
        "custom_components.homeconnect.api.time",
        SimpleNamespace(monotonic=lambda: now, time=time.time),
    )


async def test_nothing_is_asked_while_the_cloud_said_to_wait(
    aioclient_mock: AiohttpClientMocker,
    session: aiohttp.ClientSession,  # noqa: F811
) -> None:
    aioclient_mock.get(LISTING, status=429, headers={"Retry-After": "600"}, json={})
    api = api_for(session)
    with at(1000.0):
        with pytest.raises(HomeConnectTooManyRequests) as refused:
            await api.appliances()
        assert refused.value.retry_after == 600
        assert aioclient_mock.call_count == 1
    with at(1599.0):
        with pytest.raises(HomeConnectTooManyRequests) as held:
            await api.appliances()
        assert held.value.retry_after == pytest.approx(1.0)
        assert aioclient_mock.call_count == 1


async def test_asking_resumes_once_the_wait_is_over(
    aioclient_mock: AiohttpClientMocker,
    session: aiohttp.ClientSession,  # noqa: F811
) -> None:
    aioclient_mock.get(LISTING, status=429, headers={"Retry-After": "600"}, json={})
    api = api_for(session)
    with at(1000.0), pytest.raises(HomeConnectTooManyRequests):
        await api.appliances()
    aioclient_mock.clear_requests()
    aioclient_mock.get(LISTING, json={"data": {"homeappliances": []}})
    with at(1600.0):
        assert await api.appliances() == []
    assert aioclient_mock.call_count == 1


async def test_a_refusal_that_names_no_wait_holds_nothing_back(
    aioclient_mock: AiohttpClientMocker,
    session: aiohttp.ClientSession,  # noqa: F811
) -> None:
    aioclient_mock.get(LISTING, status=429, json={})
    api = api_for(session)
    for _ in range(2):
        with pytest.raises(HomeConnectTooManyRequests):
            await api.appliances()
    assert aioclient_mock.call_count == 2
