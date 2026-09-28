"""The optional browser helper only detects capabilities."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "src/nabiz/console/static/js/voice_provider.js"


def test_helper_has_no_capture_network_or_persistence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "indexedDB",
                      "getUserMedia(", "MediaRecorder(", "SpeechRecognition(", "speechSynthesis.speak("):
        assert forbidden not in source
    assert "Bu ses yapaydır" in source
    assert not re.search("[\u2013\u2014]", source)


def test_capability_helpers_in_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (
        f"const {{ voiceCapabilities, speechPath, syntheticVoiceNotice }} = await import({json.dumps(SCRIPT.as_uri())});"
        "const none = voiceCapabilities({});"
        "if (speechPath(false, none) !== 'typing') throw new Error('typing fallback');"
        "const browser = voiceCapabilities({ webkitSpeechRecognition: function() {} });"
        "if (speechPath(false, browser) !== 'browser') throw new Error('browser fallback');"
        "const server = { ...browser, microphone: true };"
        "if (speechPath(true, server) !== 'provider') throw new Error('provider path');"
        "if (!syntheticVoiceNotice('en').includes('synthetic')) throw new Error('notice missing');"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
