"""Moved to :mod:`ibb_mcp.alerts.engine`; this name is the same module object.

Aliased through ``sys.modules`` rather than re-exported name by name, so that code written
before the move keeps working completely: ``nabiz.alerts.engine.X`` and
``ibb_mcp.alerts.engine.X`` are one attribute, private helpers and monkeypatching included.
See :mod:`nabiz.alerts`.
"""

import sys

from ibb_mcp.alerts import engine as _moved

sys.modules[__name__] = _moved
