"""Retry shim for flaky local DNS resolvers.

Some home/branch routers intermittently answer NXDOMAIN (``getaddrinfo failed``)
for the long CNAME chains behind ``*.services.ai.azure.com`` and
``*.azure-api.net``. A retry a second later succeeds. Importing this module and
calling :func:`install` makes every ``socket.getaddrinfo`` in the process retry
briefly, so demo and proof scripts do not die on a transient resolver blip.
"""
from __future__ import annotations

import socket
import time

_ORIGINAL = socket.getaddrinfo
_INSTALLED = False


def _retrying_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
    delay = 0.3
    for attempt in range(9):
        try:
            return _ORIGINAL(host, port, *args, **kwargs)
        except socket.gaierror:
            if attempt == 8 or host in (None, "", "localhost", "127.0.0.1", "::1"):
                raise
            time.sleep(delay)
            delay = min(delay * 1.6, 3.0)
    raise socket.gaierror("unreachable")


def install() -> None:
    global _INSTALLED
    if not _INSTALLED:
        socket.getaddrinfo = _retrying_getaddrinfo  # type: ignore[assignment]
        _INSTALLED = True
