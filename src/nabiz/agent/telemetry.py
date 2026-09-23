"""Moved to :mod:`ibb_mcp.telemetry`; this name is the same module object.

The tracing shim moved into the server package on 2026-09-23, because ``ibb_mcp.http`` and
``ibb_mcp.server`` make spans and ``ibb_mcp`` imports nothing from ``nabiz`` (DECISIONS #8).
Aliased through ``sys.modules`` rather than re-exported name by name: ``setup_telemetry``
writes module globals, and two module objects would mean two tracers, one of them never
configured.
"""

import sys

from ibb_mcp import telemetry as _moved

sys.modules[__name__] = _moved
