"""The browser card registry keeps untrusted card data inert and map focus stable."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"
CARDS = STATIC / "js" / "chat_cards.js"
MAP = STATIC / "js" / "chat_card_map.js"
CSS = STATIC / "css" / "chat_cards.css"

CATALOG = {
    "tr": {
        "ui.cards.sources": "Kaynak", "ui.cards.unknown_part": "Bilinmeyen bölüm",
        "ui.cards.fallback": "Bu kart gösterilemedi; bilgisi aşağıda.",
        "ui.cards.expand_map": "Haritayı büyüt", "ui.cards.close_map": "Haritayı kapat",
        "ui.cards.map_failed": "Harita yüklenemedi.", "ui.cards.map_points": "Haritadaki konumlar",
        "ui.cards.status_preparing": "Hazırlanıyor", "ui.cards.status_needs_input": "Bilgi bekliyor",
        "ui.cards.status_ready": "Hazır", "ui.cards.status_awaiting_confirmation": "Onayınızı bekliyor",
        "ui.cards.status_done": "Tamamlandı", "ui.cards.status_unavailable": "Kullanılamıyor",
        "ui.cards.status_error": "Hata",
        "ui.cards.freshness_guncel": "güncel", "ui.cards.freshness_kayitli": "kayıtlı",
        "ui.cards.freshness_tarife": "tarifeye göre", "ui.cards.freshness_dogrulanamadi": "doğrulanamadı",
        "ui.cards.action_use_location": "Konumumu kullan", "ui.cards.action_type_place": "Yer yaz",
        "ui.cards.action_listen": "Dinle", "ui.cards.action_remember_here": "Burada hatırla",
        "ui.cards.action_remember_always": "Her zaman hatırla", "ui.cards.action_change": "Değiştir",
        "ui.cards.action_forget": "Unut", "ui.cards.action_save_calendar": "Takvime kaydet",
        "ui.cards.action_export_ics": "Takvim dosyası indir",
        "ui.cards.action_review_report": "Bildirimi gözden geçir", "ui.cards.action_send": "Gönder",
        "ui.cards.action_open_official": "Resmî kaynağı aç",
    },
    "en": {
        "ui.cards.sources": "Source", "ui.cards.unknown_part": "Unknown section",
        "ui.cards.fallback": "This card could not be shown; its information is below.",
        "ui.cards.expand_map": "Expand map", "ui.cards.close_map": "Close map",
        "ui.cards.map_failed": "Map could not load.", "ui.cards.map_points": "Map locations",
        "ui.cards.status_preparing": "Preparing", "ui.cards.status_needs_input": "Needs information",
        "ui.cards.status_ready": "Ready", "ui.cards.status_awaiting_confirmation": "Awaiting your approval",
        "ui.cards.status_done": "Done", "ui.cards.status_unavailable": "Unavailable",
        "ui.cards.status_error": "Error",
        "ui.cards.freshness_guncel": "current", "ui.cards.freshness_kayitli": "recorded",
        "ui.cards.freshness_tarife": "scheduled", "ui.cards.freshness_dogrulanamadi": "unverified",
        "ui.cards.action_use_location": "Use my location", "ui.cards.action_type_place": "Type a place",
        "ui.cards.action_listen": "Listen", "ui.cards.action_remember_here": "Remember here",
        "ui.cards.action_remember_always": "Always remember", "ui.cards.action_change": "Change",
        "ui.cards.action_forget": "Forget", "ui.cards.action_save_calendar": "Save to calendar",
        "ui.cards.action_export_ics": "Download calendar file",
        "ui.cards.action_review_report": "Review report", "ui.cards.action_send": "Send",
        "ui.cards.action_open_official": "Open official source",
    },
}


def test_catalog_covers_card_text_and_sources_are_safe() -> None:
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    code = CARDS.read_text(encoding="utf-8") + MAP.read_text(encoding="utf-8")
    literal_keys = set(re.findall(r"t\(['\"](ui\.cards\.[a-z_]+)['\"]", code))
    assert literal_keys <= CATALOG["tr"].keys()
    assert {"ui.cards.action_" + action for action in (
        "use_location", "type_place", "listen", "remember_here", "remember_always",
        "change", "forget", "save_calendar", "export_ics", "review_report", "send", "open_official",
    )} <= CATALOG["tr"].keys()
    assert {"ui.cards.status_" + status for status in (
        "preparing", "needs_input", "ready", "awaiting_confirmation", "done", "unavailable", "error",
    )} <= CATALOG["tr"].keys()
    assert {"ui.cards.freshness_" + freshness for freshness in (
        "guncel", "kayitli", "tarife", "dogrulanamadi",
    )} <= CATALOG["tr"].keys()
    for source in (CARDS, MAP, CSS):
        content = source.read_text(encoding="utf-8")
        assert len(content.splitlines()) <= 300
        assert "btn-primary" not in content
        assert "setInterval" not in content
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", content)


DOM = r"""
class Node {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.parentElement = null; this.dataset = {};
    this.attrs = {}; this.listeners = {}; this.className = ''; this.hidden = false; this.open = false;
    this._text = ''; this.id = '';
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  removeAttribute(name) { delete this.attrs[name]; }
  append(...nodes) { nodes.forEach(node => { node.remove(); node.parentElement = this; this.children.push(node); }); }
  before(node) { node.remove(); const items = this.parentElement.children;
    node.parentElement = this.parentElement; items.splice(items.indexOf(this), 0, node); }
  after(node) { node.remove(); const items = this.parentElement.children;
    node.parentElement = this.parentElement; items.splice(items.indexOf(this) + 1, 0, node); }
  remove() { if (this.parentElement) {
    const items = this.parentElement.children; items.splice(items.indexOf(this), 1);
  } this.parentElement = null; }
  get isConnected() { return this === document || !!this.parentElement?.isConnected; }
  matches(selector) {
    if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
    const action = selector.match(/^\[data-card-action="([^"]+)"\]$/);
    if (action) return this.dataset.cardAction === action[1];
    return this.tagName === selector;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll(selector)])
    .filter(node => node.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  dispatchEvent(event) { (this.listeners[event.type] || []).forEach(callback => callback(event)); }
  focus() { document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent({type: 'close'}); }
}
const document = new Node('document');
document.createElement = tag => new Node(tag);
document.createComment = () => new Node('comment');
document.head = new Node('head'); document.body = new Node('body');
document.append(document.head, document.body);
globalThis.document = document;
globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail; } };
const observers = [];
globalThis.IntersectionObserver = class {
  constructor(callback) { this.callback = callback; observers.push(this); }
  observe(node) { this.node = node; }
  disconnect() { this.node = null; }
};
let invalidations = 0, markers = 0, mapRemovals = 0;
const window = {scrollY: 137, innerHeight: 800, scrollTo(_x, y) { this.scrollY = y; },
  L: {map() { return {setView() {}, fitBounds() {}, invalidateSize() { invalidations++; },
    remove() { mapRemovals++; }}; },
    tileLayer() { return {on() { return this; }, addTo() { return this; }}; },
    marker() { markers++; return {bindPopup(node) { if (node.tagName !== 'span') throw Error('unsafe popup');
      return this; }, addTo() { return this; }}; }} };
globalThis.window = window;
globalThis.requestAnimationFrame = callback => callback();
"""


def run_cards(tmp_path, code: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "card_harness.mjs"
    script.write_text(
        f"import * as cards from {json.dumps(CARDS.as_uri())};\n"
        f"import {json.dumps(MAP.as_uri())};\n{DOM}\n{code}\n",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_registry_fallback_filtering_and_map_dialog(tmp_path) -> None:
    values = run_cards(tmp_path, r"""
const host = document.body;
const base = (type, id, extra = {}) => ({v: 1, id, conversation_id: null, message_id: null,
  type, status: 'ready', title: 'A safe title', body: {text: 'Some data'}, sources: [], actions: [],
  sensitive: false, ...extra});
let rendered = 0, events = [], mapNavigation = 0;
document.addEventListener('nabiz:card-action', event => events.push(event.detail));
document.addEventListener('nabiz:show-on-map', () => mapNavigation++);
const capped = cards.validateCard(base('info', '', {title: 'A'.repeat(5000), body: {
  text: 'B'.repeat(5000), items: Array.from({length: 40}, (_, i) => i)},
  sources: Array.from({length: 40}, () => ({label: 'Source'}))}));
const invalidType = cards.validateCard(base('wrong', '', {actions: ['rm -rf']}));
cards.registerCardType('route', card => { rendered++; const node = document.createElement('p');
  node.textContent = card.body.text; return node; });
cards.registerCardType('event', () => { throw Error('renderer failure'); });
cards.registerCardType('calendar_draft', () => document.createElement('p'));
const normal = cards.appendCard(host, base('route', 'r1', {actions: ['listen']}), {messageId: 'm1'});
const failed = cards.appendCard(host, base('event', 'e1'), {messageId: 'm1'});
const unknown = cards.appendCard(host, base('unknown', 'u1', {title: '<script>bad()</script>Place',
  actions: ['rm -rf', 'open_official'], sources: [{label: '<b>Site</b>', url: 'javascript:bad()',
  freshness: 'kayitli', source_time: '2026-09-27T09:20:00+03:00'}]}), {messageId: 'm1'});
const malicious = cards.appendCard(host, base('info', 'i1', {body: {text: '<script>bad()</script>Hello'},
  actions: ['open_official', 'listen', 'rm -rf'], sources: [{label: 'Site', url: 'http://unsafe.test'}]}),
  {messageId: 'm1'});
const saved = cards.appendCard(host, base('calendar_draft', 'c1', {actions: ['change', 'save_calendar',
  'export_ics', 'open_official'], sources: [{label: 'Source', url: 'https://safe.test/path'}]}),
  {messageId: 'm1', restored: true});
const sensitive = cards.appendCard(host, base('info', 'i2', {actions: ['listen'], sensitive: true}),
  {messageId: 'm1'});
const noPointMap = cards.appendCard(host, base('map', 'map-empty', {body: {points: []},
  actions: ['expand_map']}), {messageId: 'm1'});
const maxCards = cards.renderCards(host, Array.from({length: 7}, (_, i) => base('info', `bulk-${i}`)),
  {messageId: 'm1'}).length;
const listen = normal.querySelector('[data-card-action="listen"]');
listen.dispatchEvent({type: 'click'}); listen.dispatchEvent({type: 'click'});
const mapCard = cards.appendCard(host, base('map', 'map1', {body: {points: [
  {lat: 41.01, lon: 29.02, label: '<script>Bad</script> Kadıköy'},
  {lat: 41.02, lon: 29.03, label: 'Levent'}]}, actions: ['expand_map']}),
  {messageId: 'm1'});
const privateMap = cards.appendCard(host, base('map', 'private-map', {body: {points: [
  {lat: 41.03, lon: 29.04, label: 'Private point'}]}, actions: ['expand_map'], sensitive: true}),
  {messageId: 'm1'});
const mapFrame = mapCard.querySelector('.chat-card-map-frame');
const beforeVisible = invalidations;
observers.forEach(observer => observer.callback([{isIntersecting: true}]));
await Promise.resolve(); await Promise.resolve();
const expand = mapCard.querySelector('[data-card-action="expand_map"]');
expand.dispatchEvent({type: 'click'});
const dialog = document.body.querySelector('dialog');
const moved = dialog && dialog.querySelector('.chat-card-map-frame') === mapFrame;
window.scrollY = 300;
dialog.querySelector('button').dispatchEvent({type: 'click'});
const restoredFrame = mapCard.querySelector('.chat-card-map-frame') === mapFrame;
expand.dispatchEvent({type: 'click'});
const secondDialog = document.body.querySelector('dialog');
window.scrollY = 250;
secondDialog.dispatchEvent({type: 'cancel', preventDefault() {}});
const escapeRestored = document.activeElement === expand && window.scrollY === 137
  && mapCard.querySelector('.chat-card-map-frame') === mapFrame;
console.log(JSON.stringify({rendered, failedFallback: !!failed.querySelector('.chat-card-fallback'),
  capped: [capped.card.title.length, capped.card.body.text.length, capped.card.body.items.length,
    capped.card.sources.length], invalidType: invalidType.ok, maxCards,
  unknownFallback: !!unknown.querySelector('.chat-card-fallback'), unknownButtons: unknown.querySelectorAll('button').length,
  recordedStamp: unknown.textContent.includes('kayıtlı · 27.09 09:20'),
  scriptNodes: document.querySelectorAll('script').length, unsafeLinks: malicious.querySelectorAll('a').length,
  cleanBody: malicious.textContent.includes('Hello') && !malicious.textContent.includes('bad()'),
  savedActions: saved.querySelectorAll('button').map(node => node.dataset.cardAction),
  sensitiveButtons: sensitive.querySelectorAll('button').length,
  emptyMapButtons: noPointMap.querySelectorAll('button').length,
  listenEvents: events.filter(event => event.card_id === 'r1').length,
  listenerDisabled: listen.getAttribute('aria-disabled'), beforeVisible, invalidations, markers,
  privateMapList: privateMap.querySelector('.chat-card-map-points').querySelectorAll('li').length,
  privateMapHidden: privateMap.querySelector('.chat-card-map-frame').hidden,
  privateMapButtons: privateMap.querySelectorAll('button').length,
  moved, restoredFrame, escapeRestored, focusRestored: document.activeElement === expand, scrollY: window.scrollY,
  mapNavigation, mapRemovals, mapStatus: mapCard.dataset.cardStatus}));
""")
    assert values == {
        "rendered": 1, "failedFallback": True, "unknownFallback": True, "unknownButtons": 0,
        "capped": [120, 600, 20, 20], "invalidType": False, "maxCards": 6,
        "recordedStamp": True,
        "scriptNodes": 0, "unsafeLinks": 0, "cleanBody": True,
        "savedActions": ["open_official"], "sensitiveButtons": 0, "emptyMapButtons": 0,
        "listenEvents": 1, "listenerDisabled": "true", "beforeVisible": 0,
        "privateMapList": 1, "privateMapHidden": True, "privateMapButtons": 0,
        "invalidations": 5, "markers": 2, "moved": True, "restoredFrame": True, "escapeRestored": True,
        "focusRestored": True, "scrollY": 137, "mapNavigation": 0, "mapRemovals": 0,
        "mapStatus": "ready",
    }


def test_new_javascript_modules_parse() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in (CARDS, MAP):
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
