"""Checks for the citizen page's optional browser voice controls."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
VOICE_JS = STATIC / "js" / "voice.js"
VOICE_CSS = STATIC / "css" / "voice.css"
INDEX = STATIC / "index.html"
DASHES = (chr(0x2014), chr(0x2013))


def test_voice_files_exist_and_the_page_mounts_them() -> None:
    """The voice module follows the citizen entry point and its stylesheet exists."""
    html = INDEX.read_text(encoding="utf-8")
    voice_script = '<script type="module" src="/js/voice.js"></script>'
    assert VOICE_JS.is_file()
    assert VOICE_CSS.is_file()
    assert html.count(voice_script) == 1
    assert html.index('src="/js/voice.js"') > html.index('src="/js/citizen.js"')
    first_module = re.search(r'<script type="module" src="([^"]+)"', html)
    assert first_module and first_module.group(1) == "/js/citizen.js"


def test_disclosure_comes_before_the_speech_code() -> None:
    """Explain the provider transfer before the capability name appears in the module."""
    source = VOICE_JS.read_text(encoding="utf-8")
    disclosure_at = source.index("const DISCLOSURE")
    recognition_at = source.index("webkitSpeechRecognition")
    disclosure = source[disclosure_at:recognition_at]
    assert disclosure_at < recognition_at
    assert "sağlayıcısının sunucusuna" in disclosure
    assert "ses kaydı tutmaz" in disclosure
    assert "tr-TR" in source


def test_voice_script_keeps_nothing_and_calls_no_one() -> None:
    """Voice handling stays in the browser without persistence or network APIs."""
    source = VOICE_JS.read_text(encoding="utf-8")
    forbidden = (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "MediaRecorder",
        "getUserMedia",
        "icon(",
    )
    for item in forbidden:
        assert item not in source


def test_voice_text_has_no_dash_eta_or_kanca() -> None:
    """The added interface text follows the citizen page's copy rules."""
    for path in (VOICE_JS, VOICE_CSS):
        source = path.read_text(encoding="utf-8")
        for dash in DASHES:
            assert dash not in source
        assert not re.search(r"\bETA\b", source)
        assert "kanca" not in source.lower()


def test_pure_helpers_in_node() -> None:
    """Pure helpers can be imported without a browser runtime."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module_url = json.dumps(VOICE_JS.as_uri())
    script = (
        f"const {{ pickVoice, recognitionMessage, confirmPrompt }} = await import({module_url});"
        "const voices = [{ lang: 'en-US' }, { lang: 'tr-TR' }];"
        "if (pickVoice(voices).lang !== 'tr-TR') throw new Error('exact Turkish voice not selected');"
        "if (pickVoice([{ lang: 'tr' }]).lang !== 'tr') throw new Error('Turkish fallback not selected');"
        "if (pickVoice([]) !== null) throw new Error('empty voices must return null');"
        "if (!recognitionMessage('not-allowed').includes('yazarak')) throw new Error('fallback text missing');"
        "if (confirmPrompt('otobüs kaçta') !== 'Seni şöyle anladım: \"otobüs kaçta\"') "
        "throw new Error('confirmation prompt differs');"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
