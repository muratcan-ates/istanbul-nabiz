"""On-device conversation storage and panel contracts."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
STORE = STATIC / "js" / "conversations.js"
UI = STATIC / "js" / "conversations-ui.js"
CSS = STATIC / "css" / "conversations.css"


def source(path) -> str:
    return path.read_text(encoding="utf-8")


def test_conversation_store_exports_the_required_api() -> None:
    text = source(STORE)
    for name in ("saveTurn", "list", "load", "remove", "clearAll", "purgeOlderThan", "newConversation"):
        assert re.search(rf"\b{name}\b", text)
    assert re.search(r"export\s*\{[^}]*\bsaveTurn\b", text, re.S)


def test_conversation_record_has_the_documented_fields() -> None:
    text = source(STORE)
    assert "{ id: makeId(), title: 'Yeni sohbet', createdAt: now, updatedAt: now, turns: [] }" in text
    assert "role," in text and "content:" in text and "at:" in text


def test_store_uses_indexeddb_then_localstorage_then_memory() -> None:
    text = source(STORE)
    assert "indexedDB.open" in text
    assert "globalThis.localStorage" in text
    assert "memoryRecords" in text
    assert "storageMode = 'memory'" in text


def test_turn_content_and_conversation_length_are_bounded() -> None:
    text = source(STORE)
    assert "const MAX_CONTENT_LENGTH = 4000" in text
    assert "const MAX_TURNS = 80" in text
    assert "slice(0, MAX_CONTENT_LENGTH)" in text
    assert "slice(-MAX_TURNS)" in text


def test_sensitive_text_is_replaced_before_storage() -> None:
    text = source(STORE)
    assert "turn.sensitive === true" in text
    assert "SENSITIVE_TEXT.test(detectionText)" in text
    assert "[acil yönlendirme]" in text
    assert "privateContent ? REDACTED_TEXT : content" in text


def test_emergency_responses_are_replaced_before_storage() -> None:
    text = source(STORE)
    assert "turn.emergency === true" in text
    assert "turn.mode === 'redirect'" in text
    assert "EMERGENCY_TEXT.test(detectionText)" in text


def test_title_uses_the_first_user_question_without_a_model_call() -> None:
    text = source(STORE)
    assert "savedTurn.role === 'user'" in text
    assert "savedTurn.content.slice(0, 48)" in text
    assert "fetch(" not in text and "model" not in text.lower()


def test_conversations_expire_after_thirty_days_from_creation() -> None:
    text = source(STORE)
    assert "const RETENTION_DAYS = 30" in text
    assert "async function purgeOlderThan(days = RETENTION_DAYS" in text
    assert "timestamp(record.createdAt) >= cutoff" in text
    assert "purgeOlderThan(30)" in source(UI)


def test_compaction_note_uses_the_history_limit_and_required_copy() -> None:
    text = source(STORE)
    assert "count <= HISTORY_TURNS * 2" in text
    assert "Önceki mesajlar kısaltılarak gönderiliyor; yalnız son ${kept} soru hatırlanıyor." in text
    assert "compactionNote(conversation.turns.length, HISTORY_TURNS)" in source(UI)


def test_panel_has_the_required_empty_and_privacy_copy() -> None:
    text = source(UI)
    assert "Henüz sohbet yok. Sorduğunuz her şey yalnız bu cihazda saklanır." in text
    assert "Sohbetleriniz yalnız bu cihazda, 30 gün saklanır. Sunucuya kaydedilmez." in text
    assert "Bu tarayıcı geçmişi saklamıyor." in text
    assert "\u2014" not in text and "\u2013" not in text


def test_panel_exposes_new_delete_and_delete_all_actions() -> None:
    text = source(UI)
    assert "function mountConversations({ root, onOpen = () => {}, onNew = () => {} })" in text
    assert "root.classList.add('convo-root')" in text
    for label in ("Yeni sohbet", "Hepsini sil", "Sil", "Bu sohbet bu cihazdan silinsin mi?"):
        assert label in text
    assert "Tüm sohbetler bu cihazdan silinsin mi?" in text


def test_panel_supports_keyboard_deletion_live_updates_and_focus() -> None:
    text = source(UI)
    assert "aria-live=\"polite\"" in text
    assert "event.key !== 'Delete'" in text
    assert "statusElement.textContent = 'Sohbet silindi'" in text
    assert "buttons[Math.min(index, buttons.length - 1)]" in text
    assert "aria-expanded" in text and "panel.hidden = !panel.hidden" in text


def test_conversation_rows_render_local_dates() -> None:
    text = source(UI)
    assert "new Intl.DateTimeFormat('tr-TR'" in text
    assert "day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'" in text
    assert "date.dateTime = conversation.updatedAt" in text


def test_component_styles_use_only_prefixed_classes_and_tokens() -> None:
    text = source(CSS)
    selectors = [
        line.split("{", 1)[0].strip()
        for line in text.splitlines()
        if "{" in line and not line.lstrip().startswith("@")
    ]
    assert selectors
    for selector_group in selectors:
        for selector in selector_group.split(","):
            assert ".convo-" in selector, selector
    assert not re.search(r"#[\da-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\s*\(|\b(?:black|white|red|blue)\b", text)
    assert re.search(r"var\(--[\w-]+\)", text)


def test_component_styles_fit_small_screens_and_respect_reduced_motion() -> None:
    text = source(CSS)
    assert "@media (max-width: 48rem)" in text
    assert "min-width: 0" in text and "overflow-wrap: anywhere" in text
    assert "@media (prefers-reduced-motion: reduce)" in text
    assert "animation: none !important" in text and "transition: none !important" in text


def test_store_contains_no_network_or_server_persistence_calls() -> None:
    text = source(STORE)
    assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|/api/", text)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable; source contracts cover this module")
def test_store_behaviour_in_node_memory_fallback() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {
  clearAll, compactionNote, list, load, newConversation, purgeOlderThan, remove, saveTurn, storageStatus,
} from './src/nabiz/console/static/js/conversations.js';

await clearAll();
const convo = await newConversation();
const sensitive = await saveTurn(convo.id, { role: 'user', content: 'İlaç dozunu öğrenmek istiyorum.' });
assert.equal(sensitive.turns[0].content, '[acil yönlendirme]');
assert.equal(sensitive.title, '[acil yönlendirme]');
await saveTurn(convo.id, { role: 'assistant', content: 'Bu acil bir durum olabilir. 112 numarasını arayın.' });
let saved = await load(convo.id);
assert.equal(saved.turns[1].content, '[acil yönlendirme]');
await saveTurn(convo.id, { role: 'user', content: 'S'.repeat(5000) });
saved = await load(convo.id);
assert.equal(saved.turns[2].content.length, 4000);
assert.equal(saved.title.length, 18);
for (let index = 0; index < 82; index += 1) {
  await saveTurn(convo.id, { role: 'assistant', content: `yanıt ${index}` });
}
saved = await load(convo.id);
assert.equal(saved.turns.length, 80);
assert.match(compactionNote(13, 6), /yalnız son 6 soru hatırlanıyor/);
assert.equal(compactionNote(12, 6), '');
assert.equal((await list())[0].id, convo.id);
assert.equal(await purgeOlderThan(30, Date.now() + 31 * 86400000), 1);
assert.equal(await load(convo.id), null);
const another = await newConversation();
assert.equal(await remove(another.id), true);
await clearAll();
assert.deepEqual(await list(), []);
assert.equal((await storageStatus()).persistent, false);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
