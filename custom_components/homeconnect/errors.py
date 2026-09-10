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

"""Errors raised by the Home Connect cloud client.

Three things go wrong, and a caller treats each differently. Credentials that
are no longer good need the user to sign in again. A service that cannot be
reached is worth retrying. An appliance that will not do as it is told is
neither: the request was understood and refused, and the reason is worth
showing to whoever asked for it.
"""

from __future__ import annotations


class HomeConnectError(Exception):
    """Base class for every error raised by this integration."""


class HomeConnectAuthError(HomeConnectError):
    """Credentials were rejected and signing in again is needed."""


class HomeConnectConnectionError(HomeConnectError):
    """The service could not be reached, or answered with something unusable."""


class HomeConnectBackendError(HomeConnectConnectionError):
    """The service answered with a server side failure."""


class HomeConnectTooManyRequests(HomeConnectConnectionError):
    """The service asked us to slow down.

    Carries how long it asked for when it said, since the answer to this is to
    wait exactly that long rather than to guess.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class HomeConnectRefused(HomeConnectError):
    """The appliance understood the request and would not do it.

    A washing machine mid-cycle will not take a new programme, an oven with
    the door open will not start, and an appliance whose remote control has
    not been armed refuses everything. The cloud names the reason, and that
    name is worth passing on because it is the only thing that tells the user
    what to go and do at the machine itself.
    """

    def __init__(self, message: str, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key
