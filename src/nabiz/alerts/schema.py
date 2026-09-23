"""Moved to :mod:`ibb_mcp.alerts.schema`; this name is the same module object.

Aliased through ``sys.modules`` rather than re-exported name by name, so that code written
before the move keeps working completely: ``nabiz.alerts.schema.X`` and
``ibb_mcp.alerts.schema.X`` are one attribute, private helpers and monkeypatching included.
See :mod:`nabiz.alerts`.
"""

import sys

from ibb_mcp.alerts import schema as _moved

sys.modules[__name__] = _moved
