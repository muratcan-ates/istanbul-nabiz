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
ACTIONS = STATIC / "js" / "chat_card_actions.js"
MAP = STATIC / "js" / "chat_card_map.js"
CSS = STATIC / "css" / "chat_cards.css"

CATALOG = {
    "tr": {
        "ui.cards.sources": "Kaynak", "ui.cards.unknown_part": "Bilinmeyen bölüm",
        "ui.cards.time_unknown": "zaman bilinmiyor",
        "ui.cards.fallback": "Bu kart gösterilemedi; bilgisi aşağıda.",
        "ui.cards.expand_map": "Haritayı büyüt", "ui.cards.close_map": "Haritayı kapat",
        "ui.cards.map_failed": "Harita yüklenemedi.", "ui.cards.map_points": "Haritadaki konumlar",
        "ui.cards.map_base": "Örnek harita altlığı; kıyılar yaklaşık",
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
        "ui.cards.action_add_outlook": "Outlook'a ekle", "ui.cards.action_confirm_resolved": "Çözüldü, onayla",
        "ui.cards.action_reopen": "Yeniden aç", "ui.cards.action_cancel": "İptal et",
        "ui.cards.action_appeal": "İtiraz et", "ui.cards.action_share": "Paylaş",
        "ui.cards.consent_use_location": "Konumunuz bu cihazda kullanılacak.",
        "ui.cards.consent_remember_here": "Bu bilgi yalnız bu sohbette hatırlanacak.",
        "ui.cards.consent_remember_always": "Bu bilgi bu tarayıcıdaki profilinize kaydedilecek.",
        "ui.cards.consent_save_calendar": "Bu plan Nabız takviminize kaydedilecek.",
        "ui.cards.consent_send": "Bu bildirim Nabız üzerinden ilgili ekibe gönderilecek.",
        "ui.cards.consent_add_outlook": "Bu olay Outlook takviminize eklenecek; Microsoft hesabınıza yazılır.",
        "ui.cards.consent_confirm_resolved": "Bu bildirimi çözüldü olarak onaylayacaksınız.",
        "ui.cards.consent_reopen": "Bu bildirim yeniden açılacak.",
        "ui.cards.consent_cancel": "Bu işlem iptal edilecek.",
        "ui.cards.consent_appeal": "Bu itiraz Nabız üzerinden ilgili ekibe gönderilecek.",
        "ui.cards.consent_share": "Yalnız başlık ve resmî kaynak adresi paylaşılacak.",
        "ui.cards.consent_kind_view": "Bu kartın görünümü değişecek.",
        "ui.cards.consent_kind_device": "Bu işlem yalnız bu cihazda uygulanacak.",
        "ui.cards.consent_kind_nabiz": "Bu işlem Nabız üzerinde kaydedilecek.",
        "ui.cards.consent_kind_external": "Bu işlem Nabız dışındaki bağlı hizmete gönderilecek.",
        "ui.cards.confirm": "Onayla", "ui.cards.dismiss": "Vazgeç",
        "ui.cards.action_unsupported": "Bu kartta desteklenmeyen bir işlem var; düğme gösterilmedi.",
        "ui.cards.action_not_ready": "Bu işlem henüz bağlı değil; hiçbir şey kaydedilmedi.",
        "ui.cards.outlook_not_connected": "Outlook bağlantısı yok; plan yalnız Nabız'da duruyor, Outlook'a eklenmedi.",
        "ui.cards.result_saved_nabiz": "Nabız takvimine kaydedildi.",
        "ui.cards.result_ics_downloaded": "Takvim dosyası indirildi.",
        "ui.cards.result_outlook_verifying": "Outlook'a ekleniyor, doğrulanıyor.",
        "ui.cards.result_outlook_added": "Outlook'a eklendi.",
        "ui.cards.result_outlook_failed": "Outlook'a eklenemedi.",
        "ui.cards.result_report_sent": "Bildirim gönderildi.",
        "ui.cards.result_resolution_confirmed": "Çözüldüğü onaylandı.",
        "ui.cards.result_reopened": "Yeniden açıldı.",
        "ui.cards.result_cancelled": "İptal edildi.",
        "ui.cards.result_appeal_sent": "İtiraz gönderildi.",
    },
    "en": {
        "ui.cards.sources": "Source", "ui.cards.unknown_part": "Unknown section",
        "ui.cards.time_unknown": "time unknown",
        "ui.cards.fallback": "This card could not be shown; its information is below.",
        "ui.cards.expand_map": "Expand map", "ui.cards.close_map": "Close map",
        "ui.cards.map_failed": "Map could not load.", "ui.cards.map_points": "Map locations",
        "ui.cards.map_base": "Sample base map; coastlines are approximate",
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
        "ui.cards.action_add_outlook": "Add to Outlook", "ui.cards.action_confirm_resolved": "Confirm resolved",
        "ui.cards.action_reopen": "Reopen", "ui.cards.action_cancel": "Cancel",
        "ui.cards.action_appeal": "Appeal", "ui.cards.action_share": "Share",
        "ui.cards.consent_use_location": "Your location will be used on this device.",
        "ui.cards.consent_remember_here": "This will be remembered only in this conversation.",
        "ui.cards.consent_remember_always": "This will be saved to your profile in this browser.",
        "ui.cards.consent_save_calendar": "This plan will be saved to your Nabız calendar.",
        "ui.cards.consent_send": "This report will be sent to the responsible team through Nabız.",
        "ui.cards.consent_add_outlook": (
            "This event will be added to your Outlook calendar and written to your Microsoft account."
        ),
        "ui.cards.consent_confirm_resolved": "You will confirm that this report is resolved.",
        "ui.cards.consent_reopen": "This report will be reopened.",
        "ui.cards.consent_cancel": "This action will be cancelled.",
        "ui.cards.consent_appeal": "This appeal will be sent to the responsible team through Nabız.",
        "ui.cards.consent_share": "Only the title and official source address will be shared.",
        "ui.cards.consent_kind_view": "This card's view will change.",
        "ui.cards.consent_kind_device": "This action will run only on this device.",
        "ui.cards.consent_kind_nabiz": "This action will be saved in Nabız.",
        "ui.cards.consent_kind_external": "This action will be sent to a connected service outside Nabız.",
        "ui.cards.confirm": "Confirm", "ui.cards.dismiss": "Dismiss",
        "ui.cards.action_unsupported": "This card contains an unsupported action; no button was shown.",
        "ui.cards.action_not_ready": "This action is not connected yet; nothing was saved.",
        "ui.cards.outlook_not_connected": "Outlook is not connected; the plan is only in Nabız and was not added to Outlook.",
        "ui.cards.result_saved_nabiz": "Saved to the Nabız calendar.",
        "ui.cards.result_ics_downloaded": "Calendar file downloaded.",
        "ui.cards.result_outlook_verifying": "Adding to Outlook, verifying.",
        "ui.cards.result_outlook_added": "Added to Outlook.",
        "ui.cards.result_outlook_failed": "Could not add to Outlook.",
        "ui.cards.result_report_sent": "Report sent.",
        "ui.cards.result_resolution_confirmed": "Resolution confirmed.",
        "ui.cards.result_reopened": "Reopened.",
        "ui.cards.result_cancelled": "Cancelled.",
        "ui.cards.result_appeal_sent": "Appeal sent.",
    },
}


def test_catalog_covers_card_text_and_sources_are_safe() -> None:
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    code = CARDS.read_text(encoding="utf-8") + ACTIONS.read_text(encoding="utf-8") + MAP.read_text(encoding="utf-8")
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
    assert {"ui.cards.consent_" + action for action in (
        "use_location", "remember_here", "remember_always", "save_calendar", "send",
        "add_outlook", "confirm_resolved", "reopen", "cancel", "appeal", "share",
    )} <= CATALOG["tr"].keys()
    assert {"ui.cards.result_" + result for result in (
        "saved_nabiz", "ics_downloaded", "outlook_verifying", "outlook_added", "outlook_failed",
        "report_sent", "resolution_confirmed", "reopened", "cancelled", "appeal_sent",
    )} <= CATALOG["tr"].keys()
    for source in (CARDS, ACTIONS, MAP, CSS):
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
  dispatchEvent(event) { (this.listeners[event.type] || []).forEach(callback => callback(event));
    return !event.defaultPrevented; }
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
globalThis.CustomEvent = class {
  constructor(type, options) { this.type = type; this.detail = options.detail;
    this.cancelable = !!options.cancelable; this.defaultPrevented = false; }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
};
const observers = [];
globalThis.IntersectionObserver = class {
  constructor(callback) { this.callback = callback; observers.push(this); }
  observe(node) { this.node = node; }
  disconnect() { this.node = null; }
};
let invalidations = 0, markers = 0, mapRemovals = 0, seaShapes = 0, baseLabels = 0, baseNote = '';
const pane = () => ({style: {}, setAttribute() {}});
const window = {scrollY: 137, innerHeight: 800, scrollTo(_x, y) { this.scrollY = y; },
  L: {map() { const panes = {}; return {setView() {}, fitBounds() {}, invalidateSize() { invalidations++; },
    remove() { mapRemovals++; }, getContainer() { return {classList: {add() {}}}; }, getPane(name) { return panes[name]; },
    createPane(name) { panes[name] = pane(); return panes[name]; }, on() {}, getZoom() { return 15; }}; },
    tileLayer() { throw Error('no map tile server'); },
    polygon() { seaShapes++; return {}; },
    divIcon(options) { return options; },
    layerGroup(layers, options) { baseNote = options.attribution; return {addTo() { return this; }}; },
    marker(_at, options) { if (options && options.interactive === false) { baseLabels++; return {}; }
      markers++; return {bindPopup(node) { if (node.tagName !== 'span') throw Error('unsafe popup');
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
document.addEventListener('nabiz:card-action', event => {
  events.push(event.detail); if (event.detail.card_id === 'r1') event.preventDefault();
});
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
const savedData = await cards.prepareCardActions(base('calendar_draft', 'c1', {actions: ['change', 'save_calendar',
  'export_ics', 'open_official'], sources: [{label: 'Source', url: 'https://safe.test/path',
  freshness: 'guncel', source_time: '2026-09-27T09:20:00+03:00'}]}), 'm1');
const saved = cards.appendCard(host, savedData,
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
await new Promise(resolve => setTimeout(resolve, 50));
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
  unknownNotice: unknown.textContent.includes('desteklenmeyen bir işlem'),
  recordedStamp: unknown.textContent.includes('kayıtlı · 27.09 09:20'),
  savedRecordedStamp: saved.textContent.includes('kayıtlı · 27.09 09:20'),
  scriptNodes: document.querySelectorAll('script').length, unsafeLinks: malicious.querySelectorAll('a').length,
  unknownTime: malicious.textContent.includes('zaman bilinmiyor'),
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
  mapNavigation, mapRemovals, mapStatus: mapCard.dataset.cardStatus, seaShapes, baseLabels, baseNote}));
""")
    assert values == {
        "rendered": 1, "failedFallback": True, "unknownFallback": True, "unknownButtons": 0,
        "capped": [120, 600, 20, 20], "invalidType": False, "maxCards": 6,
        "recordedStamp": True, "savedRecordedStamp": True, "unknownNotice": True,
        "scriptNodes": 0, "unsafeLinks": 0, "unknownTime": True, "cleanBody": True,
        "savedActions": ["open_official"], "sensitiveButtons": 1, "emptyMapButtons": 0,
        "listenEvents": 1, "listenerDisabled": "true", "beforeVisible": 0,
        "privateMapList": 1, "privateMapHidden": True, "privateMapButtons": 0,
        "invalidations": 5, "markers": 2, "moved": True, "restoredFrame": True, "escapeRestored": True,
        "focusRestored": True, "scrollY": 137, "mapNavigation": 0, "mapRemovals": 0,
        "mapStatus": "ready", "seaShapes": 3, "baseLabels": 12,
        "baseNote": "Örnek harita altlığı; kıyılar yaklaşık",
    }


def test_v01_action_normalization_linkage_and_operation_id(tmp_path) -> None:
    values = run_cards(tmp_path, r"""
const {createHash} = await import('node:crypto');
const expected = 'op-' + createHash('sha256').update('card-1\0save_calendar\0message-1').digest('hex').slice(0, 16);
const alias = cards.normalizeAction({id: 'add_calendar', label: '<b>Save</b>', kind: 'view',
  requires_consent: false});
const raised = cards.normalizeAction({id: 'listen', kind: 'nabiz', requires_consent: true,
  operation_id: 'bad-producer-id'});
const v0 = cards.fromV0({v: 0, id: 'card-1', type: 'event', status: 'ready', title: 'Event',
  linked: {event_id: 'evt-7', report_code: null, operation_id: null},
  source: {name: 'Source A', observed_at: '2026-09-27T09:20:00+03:00', freshness: 'kayitli'},
  data: {text: 'Body', sources: [{name: 'Source B', observed_at: '2026-09-26T09:20:00+03:00',
    freshness: 'kayitli'}]},
  actions: [{id: 'add_calendar', label: 'Save', kind: 'view', requires_consent: false,
    operation_id: null}, {id: 'add_outlook', operation_id: 'op-producer'}], sensitive: false});
const first = await cards.prepareCardActions({v: 1, id: 'card-1', actions: ['save_calendar',
  {id: 'add_outlook', operation_id: 'op-producer'}, 'unknown_action']}, 'message-1');
const again = await cards.prepareCardActions({v: 1, id: 'card-1', actions: ['save_calendar']}, 'message-1');
const other = await cards.prepareCardActions({v: 1, id: 'card-1', actions: ['save_calendar']}, 'message-2');
const health = cards.validateCard({v: 1, id: 'health', type: 'memory', status: 'ready', title: 'Memory',
  body: {kind: 'health'}, actions: ['remember_always', 'share', 'change'], sensitive: false});
const legacy = cards.validateCard({v: 1, id: 'legacy', type: 'info', status: 'ready', title: 'Info',
  body: {}, linked: {event_id: null, report_code: null, operation_id: null},
  linked_id: 'report:ABC', actions: []});
const invalidResult = cards.validateCard({v: 1, type: 'info', status: 'done', title: 'Info',
  body: {result: 'outlook_added_by_model'}, actions: []});
const mapLimits = cards.validateCard({v: 1, type: 'map', status: 'ready', title: 'Map',
  body: {points: Array.from({length: 70}, (_, i) => ({lat: i, lon: 0, label: 'Point'})),
    nested: {points: Array.from({length: 30}, (_, i) => i)}}, actions: []});
console.log(JSON.stringify({count: cards.CARD_ACTIONS.length,
  kind: cards.ACTION_KIND.add_outlook, consent: cards.CONSENT_ACTIONS.includes('share'),
  aliasId: alias.id, aliasKind: alias.kind, aliasConsent: alias.requires_consent, aliasLabel: alias.label,
  raisedKind: raised.kind, raisedConsent: raised.requires_consent, raisedOperation: raised.operation_id,
  v0Version: v0.v, v0Body: v0.body.text, v0Linked: v0.linked.event_id,
  v0LinkedId: v0.linked_id, v0Sources: v0.sources.length, v0Oldest: v0.source_time,
  v0Action: v0.actions[0].id, v0ProducerOperation: v0.actions[1].operation_id,
  operation: first.actions[0].operation_id, expected, stable: again.actions[0].operation_id,
  different: other.actions[0].operation_id !== expected,
  producerOperation: first.actions[1].operation_id, preparedCount: first.actions.length,
  healthSensitive: health.card.sensitive, healthActions: health.card.actions.map(action => action.id),
  legacyLinked: legacy.card.linked.report_code, legacyLinkedId: legacy.card.linked_id,
  invalidResult: invalidResult.card.body.result,
  mapLimits: [mapLimits.card.body.points.length, mapLimits.card.body.nested.points.length]}));
""")
    assert values == {
        "count": 19, "kind": "external", "consent": True,
        "aliasId": "save_calendar", "aliasKind": "nabiz", "aliasConsent": True, "aliasLabel": "Save",
        "raisedKind": "view", "raisedConsent": True, "raisedOperation": None,
        "v0Version": 1, "v0Body": "Body", "v0Linked": "evt-7", "v0LinkedId": "event:evt-7",
        "v0Sources": 2, "v0Oldest": "2026-09-26T09:20:00+03:00",
        "v0Action": "save_calendar", "v0ProducerOperation": "op-producer",
        "operation": values["expected"], "expected": values["expected"], "stable": values["expected"],
        "different": True, "producerOperation": "op-producer", "preparedCount": 2,
        "healthSensitive": True, "healthActions": ["change"],
        "legacyLinked": "ABC", "legacyLinkedId": "report:ABC", "invalidResult": None,
        "mapLimits": [60, 20],
    }


def test_v01_consent_cancelable_event_and_unhandled_status(tmp_path) -> None:
    values = run_cards(tmp_path, r"""
const host = document.body;
const base = (id, type, actions, extra = {}) => ({v: 1, id, type, status: 'ready', title: 'Plan',
  body: {}, sources: [{label: 'Official', url: 'https://official.test'}], actions, sensitive: false, ...extra});
cards.registerCardType('calendar_draft', () => document.createElement('p'));
cards.registerCardType('event', () => document.createElement('p'));
cards.registerCardType('memory', () => document.createElement('p'));
let events = [];
document.addEventListener('nabiz:card-action', event => {
  events.push(event.detail); if (event.detail.action === 'save_calendar') event.preventDefault();
});
const outlookData = await cards.prepareCardActions(base('outlook', 'calendar_draft', ['add_outlook']), 'm1');
const outlook = cards.appendCard(host, outlookData, {messageId: 'm1'});
const outlookButton = outlook.querySelector('[data-card-action="add_outlook"]');
outlookButton.dispatchEvent({type: 'click'});
const beforeConsent = events.length;
const row = outlook.querySelector('.chat-card-consent');
const hiddenWhileConsent = outlook.querySelector('.chat-card-actions').hidden;
row.querySelector('.btn-quiet').dispatchEvent({type: 'click'});
const dismissed = events.length === 0 && !outlook.querySelector('.chat-card-consent')
  && document.activeElement === outlookButton && !outlook.querySelector('.chat-card-actions').hidden;
outlookButton.dispatchEvent({type: 'click'});
const describedBy = outlook.querySelector('.chat-card-consent').querySelector('.btn').getAttribute('aria-describedby');
outlook.querySelector('.chat-card-consent').querySelector('.btn').dispatchEvent({type: 'click'});
const focusBack = document.activeElement === outlookButton;
const unhandled = outlook.textContent.includes('Outlook bağlantısı yok')
  && !outlook.textContent.includes("Outlook'a eklendi")
  && outlookButton.getAttribute('aria-disabled') === null;
const saveData = await cards.prepareCardActions(base('save', 'calendar_draft', ['save_calendar']), 'm1');
const save = cards.appendCard(host, saveData, {messageId: 'm1'});
save.querySelector('[data-card-action="save_calendar"]').dispatchEvent({type: 'click'});
const confirm = save.querySelector('.chat-card-consent').querySelector('.btn');
confirm.dispatchEvent({type: 'click'}); confirm.dispatchEvent({type: 'click'});
const escalatedData = await cards.prepareCardActions(base('escalated', 'event', [
  {id: 'open_official', requires_consent: true}]), 'm1');
const escalated = cards.appendCard(host, escalatedData, {messageId: 'm1'});
escalated.querySelector('[data-card-action="open_official"]').dispatchEvent({type: 'click'});
const genericConsent = escalated.querySelector('.chat-card-consent').textContent.includes('Nabız dışındaki');
const restoredData = await cards.prepareCardActions(base('restored', 'event', [
  'share', 'save_calendar', 'open_official']), 'm1');
const restored = cards.appendCard(host, restoredData, {messageId: 'm1', restored: true});
const sensitiveData = await cards.prepareCardActions(base('sensitive', 'event', [
  'share', 'save_calendar', 'listen'], {sensitive: true}), 'm1');
const raisedSensitive = cards.appendCard(host, base('raised', 'info', [{id: 'listen', requires_consent: true}],
  {sensitive: true}), {messageId: 'm1'});
const sensitive = cards.appendCard(host, sensitiveData, {messageId: 'm1'});
const memory = cards.appendCard(host, base('memory', 'memory', ['remember_here', 'remember_always']),
  {messageId: 'm1'});
const verifying = cards.appendCard(host, base('verifying', 'calendar_draft', [],
  {status: 'done', body: {result: 'outlook_verifying'}}), {messageId: 'm1'});
console.log(JSON.stringify({beforeConsent, hiddenWhileConsent, dismissed, unhandled, describedBy, focusBack,
  events: events.map(event => ({action: event.action, kind: event.kind,
    consent: event.requires_consent, operation: event.operation_id,
    consented: event.consented_at, message: event.message_id})),
  savedDisabled: save.querySelector('[data-card-action="save_calendar"]').getAttribute('aria-disabled'),
  restoredActions: restored.querySelectorAll('button').map(button => button.dataset.cardAction),
  sensitiveActions: sensitive.querySelectorAll('button').map(button => button.dataset.cardAction),
  memoryButtons: memory.querySelectorAll('button').length, genericConsent,
  raisedSensitiveButtons: raisedSensitive.querySelectorAll('button').length,
  verifyingText: verifying.textContent.includes("Outlook'a ekleniyor, doğrulanıyor.")
    && !verifying.textContent.includes("Outlook'a eklendi.")}));
""")
    assert values["beforeConsent"] == 0
    assert values["hiddenWhileConsent"] is True
    assert values["dismissed"] is True
    assert values["unhandled"] is True
    assert values["describedBy"] and values["describedBy"].startswith("chat-card-consent-")
    assert values["focusBack"] is True
    assert len(values["events"]) == 2
    assert values["events"][0]["action"] == "add_outlook"
    assert values["events"][0]["kind"] == "external"
    assert values["events"][0]["consent"] is True
    assert values["events"][0]["operation"].startswith("op-")
    assert values["events"][0]["consented"]
    assert values["events"][0]["message"] == "m1"
    assert values["events"][1]["action"] == "save_calendar"
    assert values["events"][1]["kind"] == "nabiz"
    assert values["events"][1]["operation"].startswith("op-")
    assert values["savedDisabled"] == "true"
    assert values["restoredActions"] == ["open_official"]
    assert values["sensitiveActions"] == ["listen"]
    assert values["memoryButtons"] == 0
    assert values["raisedSensitiveButtons"] == 0
    assert values["genericConsent"] is True
    assert values["verifyingText"] is True


def test_new_javascript_modules_parse() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in (CARDS, ACTIONS, MAP):
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
