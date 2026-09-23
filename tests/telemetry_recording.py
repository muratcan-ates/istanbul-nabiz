"""An in-memory OpenTelemetry tracer provider: just enough of the API to record spans.

Shared by ``test_agent_telemetry.py`` and ``test_server_security.py``. It lives in its own
module rather than in a test file because importing one test module from another only works
when the repository root happens to be on ``sys.path``: ``python -m pytest`` puts it there,
the ``pytest`` console script does not. ``tests/`` itself is always importable, the same way
``conftest`` is.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from nabiz.agent import telemetry


class RecordedSpan:
    def __init__(self, name: str, parent: RecordedSpan | None, options: dict[str, Any]) -> None:
        self.name = name
        self.parent = parent
        self.options = options
        self.attributes: dict[str, Any] = {}
        self.status: Any = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: Any) -> None:
        self.status = status

    def is_recording(self) -> bool:
        return True


class RecordingTracer:
    def __init__(self) -> None:
        self.finished: list[RecordedSpan] = []
        self._stack: list[RecordedSpan] = []

    @contextlib.contextmanager
    def start_as_current_span(self, name: str, **options: Any) -> Iterator[RecordedSpan]:
        recorded = RecordedSpan(name, self._stack[-1] if self._stack else None, options)
        self._stack.append(recorded)
        try:
            yield recorded
        finally:
            self._stack.pop()
            self.finished.append(recorded)

    def named(self, name: str) -> list[RecordedSpan]:
        return [span for span in self.finished if span.name == name]

    def one(self, name: str) -> RecordedSpan:
        matches = self.named(name)
        assert len(matches) == 1, f"expected exactly one {name!r} span, got {len(matches)}"
        return matches[0]

    def every_value(self) -> str:
        return " ".join(str(value) for span in self.finished for value in span.attributes.values())


class RecordingProvider:
    def __init__(self) -> None:
        self.tracer = RecordingTracer()

    def get_tracer(self, scope: str) -> RecordingTracer:
        assert scope == telemetry.SCOPE
        return self.tracer
