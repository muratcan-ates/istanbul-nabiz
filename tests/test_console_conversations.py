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
    assert "schema: 2" in text and "scoped: []" in text and "links: []" in text and "trimmed: 0" in text
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
    assert "SENSITIVE_REDACTED_TEXT" in text
    assert "redacted = emergency ? 'emergency' : 'sensitive'" in text


def test_emergency_responses_are_replaced_before_storage() -> None:
    text = source(STORE)
    assert "turn.emergency === true" in text
    assert "turn.mode === 'redirect'" in text
    assert "EMERGENCY_TEXT.test(detectionText)" in text


def test_title_uses_the_first_user_question_without_a_model_call() -> None:
    text = source(STORE)
    assert "savedTurn.role === 'user'" in text
    assert "!savedTurn.redacted" in text and "savedTurn.content.slice(0, 48)" in text
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
    assert "conversation.trimmed > 0" in source(UI)
    assert "En eski {count} mesaj silindi" in source(UI)


def test_panel_has_the_required_empty_and_privacy_copy() -> None:
    text = source(UI)
    assert "Henüz sohbet yok. Yeni sohbet başlatarak soru sorabilirsiniz." in text
    assert "Sohbetleriniz yalnız bu tarayıcıda, oluşturulduktan sonra 30 gün saklanır. Sunucuya kaydedilmez." in text
    assert "Bu tarayıcı geçmişi saklamıyor." in text
    assert "\u2014" not in text and "\u2013" not in text


def test_panel_exposes_new_delete_and_delete_all_actions() -> None:
    text = source(UI)
    assert "function mountConversations({ root, onOpen = () => {}, onNew = () => {}, onDelete = removeWithScoped" in text
    assert "root.classList.add('convo-root')" in text
    for label in ("Yeni sohbet", "Geçmiş", "Tüm sohbetleri sil", "Sohbeti sil"):
        assert label in text
    assert "Bu sohbetin mesajları ve kartları bu tarayıcıdan silinir." in text
    assert "Tüm sohbetlerin mesajları ve kartları bu tarayıcıdan silinir." in text
    assert "<dialog" in text


def test_panel_supports_keyboard_deletion_live_updates_and_focus() -> None:
    text = source(UI)
    assert "aria-live=\"polite\"" in text
    assert "event.key !== 'Delete'" in text
    assert "announce(parts.join(' '))" in text and "statusLine.textContent = message" in text
    assert "first.focus()" in text
    assert "aria-expanded" in text and "panel.hidden = !panel.hidden" in text


def test_conversation_rows_render_local_dates() -> None:
    text = source(UI)
    assert "new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR'" in text
    assert "day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'" in text
    assert "date.dateTime = conversation.updatedAt" in text


def test_user_conversation_titles_are_excluded_from_generic_translation() -> None:
    text = source(STATIC / "js" / "i18n.js")
    excluded = re.search(r"const EXCLUDED = '([^']+)';", text)
    assert excluded and ".convo-title" in excluded.group(1).split(", ")


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
            # 27 Eyl: Hafızam, the memory card and the data reset share this stylesheet (no memory.css).
            prefixes = (".convo-", ".memory-", ".data-reset-", "#hafizam", "#veri-sil")
            assert any(prefix in selector for prefix in prefixes), selector
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
assert.equal(sensitive.turns[0].content, '[hassas bilgi saklanmadı]');
assert.equal(sensitive.turns[0].redacted, 'sensitive');
assert.equal(sensitive.title, 'Yeni sohbet');
await saveTurn(convo.id, { role: 'assistant', content: 'Bu acil bir durum olabilir. 112 numarasını arayın.' });
let saved = await load(convo.id);
assert.equal(saved.turns[1].content, '[acil yönlendirme]');
assert.equal(saved.turns[1].redacted, 'emergency');
await saveTurn(convo.id, { role: 'user', content: 'S'.repeat(5000) });
saved = await load(convo.id);
assert.equal(saved.turns[2].content.length, 4000);
assert.equal(saved.title.length, 48);
for (let index = 0; index < 82; index += 1) {
  await saveTurn(convo.id, { role: 'assistant', content: `yanıt ${index}` });
}
saved = await load(convo.id);
assert.equal(saved.turns.length, 80);
assert.equal(saved.trimmed, 5);
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable; source contracts cover this module")
def test_panel_language_changes_preserve_user_titles_focus_and_storage() -> None:
    # Double only the DOM primitives; use the real panel, store, catalogues and language event handler.
    script = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mountConversations} from './src/nabiz/console/static/js/conversations-ui.js';
import {clearAll, list, newConversation, saveTurn} from './src/nabiz/console/static/js/conversations.js';
import {setCatalogs} from './src/nabiz/console/static/js/i18n_text.js';
const catalogs = Object.fromEntries(['tr', 'en'].map(lang => [lang,
  JSON.parse(readFileSync(`src/nabiz/console/static/i18n/${lang}.json`, 'utf8'))]));
Object.assign(catalogs.en, {
  'ui.history.title': 'My conversations', 'ui.history.new': 'New conversation',
  'ui.history.toggle': 'History', 'ui.history.clear': 'Delete all conversations',
  'ui.history.delete': 'Delete conversation', 'ui.history.delete_label': 'Delete conversation: {title}',
  'ui.history.expires': 'Deleted on {date}', 'ui.history.deleted': 'Conversation deleted.',
  'ui.history.cleared': 'All conversations deleted.', 'ui.history.confirm': 'Yes, delete conversation',
  'ui.history.confirm_all': 'Yes, delete conversations',
});
const events = {}, opened = [], created = [];
const doc = {activeElement: null};
class Element {
  constructor(tag) {
    this.tagName = tag; this.ownerDocument = doc; this.children = []; this.parentElement = null;
    this.dataset = {}; this.attributes = {}; this.listeners = {}; this.hidden = false; this._text = '';
    this.className = ''; this.classList = {add: name => { this.className += ` ${name}`; }};
  }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  setAttribute(key, value) {
    this.attributes[key] = String(value);
    if (key === 'class') this.className = value;
    if (key === 'hidden') this.hidden = true;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
  }
  getAttribute(key) { return this.attributes[key] ?? null; }
  matches(selector) {
    if (selector.includes(',')) return selector.split(',').some(part => this.matches(part.trim()));
    if (selector === '[data-convo-text]') return 'convoText' in this.dataset;
    if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
    return this.tagName === selector;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  append(...nodes) { nodes.forEach(node => { node.parentElement = this; this.children.push(node); }); }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) {
    this.children.forEach(node => { node.parentElement = null; }); this.children = []; this.append(...nodes);
  }
  focus() { doc.activeElement = this; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  async emit(type, target) { for (const listener of this.listeners[type] || []) await listener({type, target}); }
  showModal() { this.open = true; }
  close() { this.open = false; for (const listener of this.listeners.close || []) listener(); }
  set innerHTML(html) {
    this.replaceChildren(); const stack = [this]; let cursor = 0;
    for (const match of html.matchAll(/<(\/?)(\w+)([^>]*)>/g)) {
      stack.at(-1)._text += html.slice(cursor, match.index); cursor = match.index + match[0].length;
      if (match[1]) { stack.pop(); continue; }
      const element = new Element(match[2]);
      for (const attribute of match[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
        element.setAttribute(attribute[1], attribute[2] || '');
      }
      stack.at(-1).append(element); stack.push(element);
    }
  }
}
doc.createElement = tag => new Element(tag);
globalThis.window = {addEventListener: (type, listener) => { (events[type] ||= []).push(listener); }};
const DateFormatter = Intl.DateTimeFormat, locales = [];
Intl.DateTimeFormat = function(locale, options) { locales.push(locale); return new DateFormatter(locale, options); };
function language(lang) {
  setCatalogs(lang, catalogs[lang], catalogs.tr);
  for (const listener of events['nabiz:lang'] || []) listener({detail: {lang}});
}
await clearAll();
const blank = await newConversation();
const userTitle = await newConversation();
await saveTurn(userTitle.id, {role: 'user', content: 'Sohbetlerim'});
const userDefaultWords = await newConversation();
await saveTurn(userDefaultWords.id, {role: 'user', content: 'Yeni sohbet'});
language('tr');
const root = new Element('aside');
const ui = mountConversations({root, onOpen: convo => opened.push(convo.id), onNew: () => created.push(true)});
await ui.ready;
const row = id => root.querySelectorAll('.convo-item').find(item => item.dataset.id === id);
const panel = root.querySelector('.convo-panel'), toggle = root.querySelector('.convo-toggle');
await root.emit('click', toggle);
const originalRows = [...root.querySelector('.convo-list').children];
const userOpen = row(userTitle.id).querySelector('.convo-open'); userOpen.focus();
const stored = JSON.stringify(await list());
language('en');
assert.equal(toggle.textContent, 'History');
assert.equal(root.getAttribute('aria-label'), 'My conversations');
assert.equal(root.querySelector('.convo-new').textContent, 'New conversation');
assert.equal(row(blank.id).querySelector('.convo-title').textContent, 'New conversation');
assert.equal(row(userTitle.id).querySelector('.convo-title').textContent, 'Sohbetlerim');
assert.equal(row(userDefaultWords.id).querySelector('.convo-title').textContent, 'Yeni sohbet');
assert.equal(row(userTitle.id).querySelector('.convo-delete').getAttribute('aria-label'), 'Delete conversation: Sohbetlerim');
assert.equal(panel.hidden, false); assert.equal(toggle.getAttribute('aria-expanded'), 'true');
assert.equal(doc.activeElement, userOpen);
assert.ok(originalRows.every((item, index) => root.querySelector('.convo-list').children[index] === item));
assert.equal(JSON.stringify(await list()), stored);
const date = row(blank.id).querySelector('.convo-date');
const dateOptions = {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'};
assert.equal(date.textContent, new DateFormatter('en-GB', dateOptions).format(new Date(date.dateTime)));
await root.emit('click', userOpen); assert.deepEqual(opened, [userTitle.id]);
language('tr');
assert.equal(toggle.textContent, 'Geçmiş');
assert.equal(row(blank.id).querySelector('.convo-title').textContent, 'Yeni sohbet');
assert.equal(row(userTitle.id).querySelector('.convo-title').textContent, 'Sohbetlerim');
assert.equal(date.textContent, new DateFormatter('tr-TR', dateOptions).format(new Date(date.dateTime)));
assert.ok(locales.includes('en-GB') && locales.includes('tr-TR'));
language('en');
await root.emit('click', row(userDefaultWords.id).querySelector('.convo-delete'));
const deleteDialog = root.querySelector('.convo-dialog');
assert.equal(deleteDialog.open, true);
assert.match(deleteDialog.textContent, /messages and cards|mesajları ve kartları/);
await deleteDialog.querySelector('.convo-confirm').emit('click');
assert.equal(root.querySelector('.convo-status').textContent, 'Conversation deleted.');
assert.equal((await list()).some(convo => convo.id === userDefaultWords.id), false);
language('tr'); assert.equal(toggle.textContent, 'Geçmiş');
await root.emit('click', root.querySelector('.convo-new'));
assert.equal(created.length, 1); assert.equal(root.querySelector('.convo-status').textContent, '');
language('en');
await root.emit('click', root.querySelector('.convo-clear'));
assert.equal(deleteDialog.open, true);
await deleteDialog.querySelector('.convo-confirm').emit('click');
assert.equal(root.querySelector('.convo-status').textContent, 'All conversations deleted.');
assert.deepEqual(await list(), []);
assert.equal(doc.activeElement, root.querySelector('.convo-new'));
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
