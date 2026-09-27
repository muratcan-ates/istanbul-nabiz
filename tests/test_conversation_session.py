"""Conversation v2 storage and active-session boundaries, with no browser or network."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

CATALOG = {
    "tr": {
        "ui.history.new": "Yeni sohbet",
        "ui.history.full": "Bu sohbet 80 mesaja ulaştı; yeni sohbette devam ediyoruz. Eski sohbet olduğu gibi duruyor.",
        "ui.history.full_hint": "Yeni sohbet önerilir",
        "ui.history.active_deleted": "Açık sohbet silindi. Yeni sohbet başladı.",
        "ui.history.linked_plans": "Bağlı {count} takvim, bildirim ya da işlem kaydı silinmez; kendi bölümünden yönetilir.",
        "ui.history.linked_kept": "{count} bağlı takvim, bildirim ya da işlem kaydı kaldı.",
        "ui.history.masked_emergency": "[acil yönlendirme]",
        "ui.history.masked_sensitive": "[hassas bilgi saklanmadı]",
    },
    "en": {
        "ui.history.new": "New chat",
        "ui.history.full": "This chat reached 80 messages; we’re continuing in a new chat. The old chat remains as it was.",
        "ui.history.full_hint": "A new chat is recommended",
        "ui.history.active_deleted": "The open chat was deleted. A new chat has started.",
        "ui.history.linked_plans": "{count} linked calendar, report, or operation items remain; manage them in their sections.",
        "ui.history.linked_kept": "{count} linked calendar, report, or operation items remain.",
        "ui.history.masked_emergency": "[emergency guidance]",
        "ui.history.masked_sensitive": "[sensitive information not saved]",
    },
}


def run_node(script: str) -> None:
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_v2_turns_masks_cards_links_and_full_limit() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
await store.clearAll();
const c = await store.newConversation();
assert.equal(c.schema, 2);
assert.deepEqual(c.scoped, []);
assert.deepEqual(c.links, []);
const sensitive = await store.saveTurn(c.id, {role:'user', content:'Sağlık ocağı nerede?', message_id:'q1'});
assert.equal(sensitive.title, 'Yeni sohbet');
assert.equal(sensitive.turns[0].content, '[hassas bilgi saklanmadı]');
assert.equal(sensitive.turns[0].redacted, 'sensitive');
const emergency = await store.saveTurn(c.id, {role:'assistant', content:'112 acil', mode:'redirect'});
assert.equal(emergency.turns[1].redacted, 'emergency');
assert.equal(emergency.turns[1].content, '[acil yönlendirme]');
await store.saveTurn(c.id, {role:'user', content:'Kartal yolculuğu', message_id:'q2'});
const raw = {v:1, id:'card-1', conversation_id:null, message_id:'a1', type:'calendar_draft',
  status:'ready', title:'Takvim', body:{text:'x'.repeat(5000)}, sources:[{label:'Kaynak',url:'https://example.org'}],
  source_time:'now', linked_id:'event:entry-1', linked:{event_id:'entry-1',report_code:null,operation_id:null},
  actions:['save_calendar','unknown'], sensitive:false, extra:'omit'};
const cards = [raw, ...Array.from({length:7}, (_, i) => ({...raw,id:`card-${i+2}`}))];
let saved = await store.saveTurn(c.id, {role:'assistant', content:'Rota hazır', mode:'answer', message_id:'a1', cards});
assert.equal(saved.turns.at(-1).cards.length, 6);
assert.equal(saved.turns.at(-1).cards[0].conversation_id, c.id);
assert.equal(saved.turns.at(-1).cards[0].body.text.length, 600);
assert.deepEqual(saved.turns.at(-1).cards[0].actions,
  [{id:'save_calendar', label:'', kind:'nabiz', requires_consent:true, operation_id:null}]);
assert.equal('extra' in saved.turns.at(-1).cards[0], false);
assert.deepEqual(saved.links, [{kind:'calendar', id:'entry-1'}]);
// Contract v0.1: stored action objects keep id, kind, consent and operation id; aliases become canonical.
const v01 = {...raw, id:'card-v01', linked:{event_id:'e1', report_code:null, operation_id:null},
  actions:[{id:'add_calendar', label:'Takvime kaydet', kind:'view', requires_consent:false, operation_id:'op-1'},
    {id:'add_outlook', label:'Outlook', operation_id:'op-2'}, {id:'bogus'}, 'listen']};
const withV01 = await store.appendCardToTurn(c.id, 'a1', v01);
const storedV01 = withV01.turns.at(-1).cards.find((card) => card.id === 'card-v01');
assert.deepEqual(storedV01.actions, [
  {id:'save_calendar', label:'Takvime kaydet', kind:'nabiz', requires_consent:true, operation_id:'op-1'},
  {id:'add_outlook', label:'Outlook', kind:'external', requires_consent:true, operation_id:'op-2'},
  {id:'listen', label:'', kind:'view', requires_consent:false, operation_id:null}]);
assert.deepEqual(storedV01.linked, {event_id:'e1', report_code:null, operation_id:null});
assert.deepEqual(withV01.links, [{kind:'calendar',id:'entry-1'},{kind:'calendar',id:'e1'}]);
const reportCard = {...raw,id:'report',linked_id:'op:wrong',linked:{event_id:null,report_code:'R-1',operation_id:null}};
const withReport = await store.appendCardToTurn(c.id, 'a1', reportCard);
assert.equal(store.linkedCounts(withReport).report, 1);
const operationCard = {...raw,id:'operation',linked_id:null,linked:{event_id:null,report_code:null,operation_id:'op-3'}};
const withOperation = await store.appendCardToTurn(c.id, 'a1', operationCard);
assert.equal(store.linkedCounts(withOperation).operation, 1);
const allLinks = {event_id:'e-multi',report_code:'R-multi',operation_id:'op-multi'};
const multiCard = {...raw,id:'multi',linked:allLinks,linked_id:null};
const withMulti = await store.appendCardToTurn(c.id, 'a1', multiCard);
assert.deepEqual(withMulti.turns.at(-1).cards.at(-1).linked, allLinks);
for (const id of Object.values(allLinks)) assert.equal(withMulti.links.some(link=>link.id===id), true);
const aliasCard = {...raw,id:'aliases',linked_id:null,actions:['remember','add_calendar','download_ics',
  {id:'open_map',operation_id:'must-be-null'}]};
const aliases = (await store.appendCardToTurn(c.id, 'a1', aliasCard)).turns.at(-1).cards.at(-1).actions;
assert.deepEqual(aliases.map(action=>action.id),
  ['remember_here','save_calendar','export_ics','expand_map']);
assert.equal(aliases[3].operation_id, null);
const legacyOnly = {...raw,id:'legacy-only',linked:undefined,linked_id:'report:ignored'};
const withoutLegacyLink = await store.appendCardToTurn(c.id, 'a1', legacyOnly);
assert.equal(withoutLegacyLink.links.some(link=>link.id === 'ignored'), false);
assert.equal(store.linkedCounts(saved).calendar, 1);
assert.equal(Date.parse(store.expiresAt(saved)) - Date.parse(saved.updatedAt), 30*86400000);
const privateCard = {...raw, id:'private', sensitive:true, title:'Kalp rahatsızlığım var',
  body:{text:'Kalp rahatsızlığım var'}, linked:{event_id:null,report_code:'R-3',operation_id:null}, actions:['send']};
saved = await store.appendCardToTurn(c.id, 'a1', privateCard);
const storedPrivate = saved.turns.at(-1).cards.at(-1);
assert.equal(storedPrivate.title, '[hassas bilgi saklanmadı]');
assert.equal(JSON.stringify(storedPrivate).includes('Kalp'), false);
assert.equal(storedPrivate.body, null);
assert.deepEqual(storedPrivate.actions, []);
assert.deepEqual(storedPrivate.linked, {event_id:null,report_code:'R-3',operation_id:null});
const healthCard = {...raw,id:'health',type:'memory',sensitive:true,title:'Özel tanı',
  body:{kind:'health',label:'Özel tanı',items:[{key:'diagnosis',label:'Özel tanı'}]},
  actions:[{id:'change',label:'Özel tanı'}],linked:{event_id:null,report_code:null,operation_id:null}};
const restoredHealth = (await store.appendCardToTurn(c.id, 'a1', healthCard)).turns.at(-1).cards.at(-1);
assert.deepEqual(restoredHealth.body, {key:null,label:'Sağlık beyanı ekle',kind:'health',
  scope_options:['conversation','profile'],items:null});
assert.equal(restoredHealth.title, 'Sağlık beyanı ekle');
assert.deepEqual(restoredHealth.actions, []);
assert.equal(JSON.stringify(restoredHealth).includes('Özel tanı'), false);
for (let i=0; i<76; i++) saved = await store.saveTurn(c.id, {role:'assistant',content:`yanıt ${i}`});
assert.equal(saved.turns.length, 80);
assert.equal(saved.trimmed, 0);
assert.equal(saved.full, true);
assert.equal(await store.saveTurn(c.id, {role:'user',content:'81. mesaj'}), null);
assert.deepEqual(await store.load(c.id), saved);
assert.equal(await store.remove(c.id), true);
assert.equal(await store.load(c.id), null);
const healthDeclaration = await store.newConversation();
const hidden = await store.saveTurn(healthDeclaration.id, {role:'user',content:'Kalp rahatsızlığım var'});
assert.equal(hidden.title, 'Yeni sohbet');
assert.equal(hidden.turns[0].content, '[hassas bilgi saklanmadı]');
assert.equal(JSON.stringify(hidden).includes('Kalp rahatsızlığım'), false);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_old_records_and_scoped_data_are_read_and_deleted_together() -> None:
    script = """
import assert from 'node:assert/strict';
const data = new Map([['nabiz.conversations.v1', JSON.stringify([
  {id:'old', title:'Eski sohbet', createdAt:'2026-09-27T00:00:00Z',
   updatedAt:'2026-09-27T00:00:00Z', links:[{kind:'report',id:'R-2'}],
   turns:[null, {role:'user',content:'Merhaba',at:'2026-09-27T00:00:00Z'},
    {role:'assistant',content:'Yanıt',cards:[{id:'legacy-card',type:'status',status:'ready',title:'Durum',
      actions:['remember_here'],linked_id:'report:R-2'}]},
    {role:'user',content:47}, {role:'invalid',content:'bad'}]},
  null, {id:'broken',turns:'not-array'}])]]);
globalThis.localStorage = {getItem:key => data.get(key) || null, setItem:(key,value) => data.set(key,value)};
const store = await import('./src/nabiz/console/static/js/conversations.js');
assert.equal((await store.list()).length, 1);
const old = await store.load('old');
assert.equal(old.schema, 2);
assert.equal(old.turns.length, 2);
assert.equal(old.turns[0].content, 'Merhaba');
assert.deepEqual(old.turns[1].cards[0].actions,
  [{id:'remember_here',label:'',kind:'device',requires_consent:true,operation_id:null}]);
assert.deepEqual(old.links, [{kind:'report',id:'R-2'}]);
assert.deepEqual(old.scoped, []);
assert.equal(old.trimmed, 0);
const updated = await store.updateScoped('old', scoped => [...scoped, {id:'mem-1',type:'need',key:'slow_walk'}]);
assert.equal(updated.scoped.length, 1);
const removed = await store.removeWithScoped('old');
assert.equal(removed.scoped[0].id, 'mem-1');
assert.deepEqual(await store.list(), []);
"""
    run_node(script)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_session_isolates_turns_restores_all_and_recovers_after_deletion() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await store.clearAll();
const loaded = [], status = {textContent:''};
const chat = {loadHistory: turns => loaded.push(turns)};
const root = {querySelector: selector => selector === '.convo-status' ? status : null};
const session = mountConversationSession({chat,root,store});
await session.keepTurn({role:'user',content:"Kadıköy'den Levent'e merdivensiz nasıl giderim?",message_id:'A1'});
const a = session.activeId();
for (let i=1; i<30; i++) await session.keepTurn({role:i%2?'assistant':'user',content:`tur ${i}`,message_id:`A${i+1}`});
assert.equal((await store.load(a)).turns.length, 30);
await session.startNew();
assert.equal(session.activeId(), null);
assert.deepEqual(loaded.at(-1), []);
await session.keepTurn({role:'user',content:'B sorusu',message_id:'B1'});
const b = session.activeId();
assert.notEqual(a,b);
assert.equal(JSON.stringify(await store.load(b)).includes('Kadıköy'), false);
await session.open(a);
assert.equal(loaded.at(-1).length, 30);
await store.remove(a);
await session.onDeleted(a);
assert.equal(session.activeId(), null);
assert.deepEqual(loaded.at(-1), []);
assert.equal(status.textContent, 'Açık sohbet silindi. Yeni sohbet başladı.');
await session.keepTurn({role:'user',content:'C sorusu',message_id:'C1'});
const c = session.activeId();
assert.notEqual(c,a); assert.notEqual(c,b);
assert.equal((await store.load(b)).turns.length, 1);
await store.remove(c);
await session.keepTurn({role:'user',content:'D sorusu',message_id:'D1'});
assert.notEqual(session.activeId(), c);
assert.match(status.textContent, /yeni bir sohbete kaydedildi/);
await store.clearAll();
await session.onClearedAll();
assert.equal(session.activeId(), null);
assert.deepEqual(loaded.at(-1), []);
await session.keepTurn({role:'user',content:'E sorusu',message_id:'E1'});
assert.equal((await store.list()).length, 1);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_81st_turn_continues_in_a_new_record_without_losing_the_old_one() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession, FULL_TEXT} from './src/nabiz/console/static/js/conversation_session.js';
await store.clearAll();
const loaded = [], status = {textContent:''};
const session = mountConversationSession({chat:{loadHistory:turns => loaded.push(turns)},
  root:{querySelector:() => status},store});
for (let i=0; i<80; i++) await session.keepTurn({role:i%2 ? 'assistant':'user',content:`Eski ${i}`});
const oldId = session.activeId(), old = await store.load(oldId);
assert.equal(old.full, true);
await session.keepTurn({role:'user',content:'Yeni soru',message_id:'q81'});
const nextId = session.activeId();
assert.notEqual(nextId, oldId);
assert.deepEqual(loaded.at(-1).map(turn => turn.content), ['Yeni soru']);
assert.equal(status.textContent, FULL_TEXT);
const card = {v:1,id:'new-card',type:'info',status:'ready',title:'Yanıt',body:{text:'Yeni bilgi'},actions:[]};
await session.keepTurn({role:'assistant',content:'Yeni yanıt',message_id:'a82',cards:[card]});
const next = await store.load(nextId);
assert.equal(next.continued_from, oldId);
assert.deepEqual(next.turns.map(turn => turn.content), ['Yeni soru','Yeni yanıt']);
assert.equal(next.turns[1].cards[0].conversation_id, nextId);
assert.deepEqual(loaded.at(-1).map(turn => turn.content), ['Yeni soru','Yeni yanıt']);
assert.deepEqual(await store.load(oldId), old);
assert.equal((await store.list()).length, 2);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_full_submit_preflight_clears_old_context_once_before_dispatch() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await store.clearAll();
let context = [];
const session = mountConversationSession({chat:{loadHistory:turns => {context = turns; }},store});
for (let i=0; i<79; i++) await session.keepTurn({role:'user',content:`Eski ${i}`});
const oldId = session.activeId(), beforeLast = await store.load(oldId);
context = beforeLast.turns;
const capture = [], bubble = [], sentContexts = [];
let replay, requests = 0, blankReached = 0;
const input = {value:''};
const form = {
  addEventListener(type, handler, inCapture) { (inCapture ? capture : bubble).push(handler); },
  async emit() {
    const event = {submitter:null,stopped:false,prevented:false,
      preventDefault() {this.prevented=true;},stopImmediatePropagation() {this.stopped=true;}};
    for (const handler of capture) await handler(event);
    if (!event.stopped) for (const handler of bubble) await handler(event);
    return event;
  },
  requestSubmit() { requests += 1; replay = this.emit(); },
};
form.addEventListener('submit', () => {
  if (!input.value.trim()) { blankReached += 1; return; }
  sentContexts.push(context.map(turn=>turn.content));
  return session.keepTurn({role:'user',content:'Yeni soru'});
}, false);
assert.equal(session.bindFullSubmit(form, input), true);
assert.equal(session.bindFullSubmit(form, input), false);
const blank = await form.emit();
assert.equal(blank.prevented, false);
assert.equal(blankReached, 1);
assert.equal(requests, 0);
input.value = 'Yeni soru';
const lastWrite = session.keepTurn({role:'user',content:'Eski 79'});
assert.equal(session.activeRecord().full, false);
context = [...beforeLast.turns, {role:'user',content:'Eski 79'}];
const first = form.emit(), duplicate = form.emit();
const intercepted = await Promise.all([first, duplicate]);
await lastWrite;
await replay;
assert.equal(intercepted.every(event=>event.prevented && event.stopped), true);
assert.equal(requests, 1);
assert.deepEqual(sentContexts, [[]]);
const next = await store.load(session.activeId());
const old = await store.load(oldId);
assert.equal(old.full, true);
assert.equal(old.turns.length, 80);
assert.equal(old.turns.at(-1).content, 'Eski 79');
assert.notEqual(next.id, oldId);
assert.equal(next.continued_from, oldId);
assert.deepEqual(next.turns.map(turn=>turn.content), ['Yeni soru']);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_retention_uses_last_update_even_for_old_records() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
const now = Date.parse('2026-09-27T12:00:00Z');
const current = '2026-09-27T12:00:00Z', old = '2026-08-27T12:00:00Z';
const data = new Map([['nabiz.conversations.v1',JSON.stringify([
  {id:'active',createdAt:old,updatedAt:current,turns:[]},
  {id:'stale',createdAt:current,updatedAt:old,turns:[]}])]]);
globalThis.localStorage = {getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value)};
const store = await import('./src/nabiz/console/static/js/conversations.js');
assert.equal(store.expiresAt(await store.load('active')), '2026-10-27T12:00:00.000Z');
assert.equal(await store.purgeOlderThan(30, now), 1);
assert.deepEqual((await store.list()).map(record=>record.id), ['active']);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_client_card_waits_for_its_assistant_turn() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await store.clearAll();
const session = mountConversationSession({chat:{loadHistory(){}},store});
const card = {v:1,id:'memory-1',type:'memory',status:'awaiting_confirmation',title:'Hafıza önerisi',
  body:{items:[{type:'need',key:'slow_walk',label:'Yavaş yürüyorum'}]},actions:['remember_here','remember_always']};
await session.addCard('answer-1', card);
await session.keepTurn({role:'user',content:'Yavaş yürüyorum',message_id:'question-1'});
await session.keepTurn({role:'assistant',content:'Bir rota buldum',message_id:'answer-1'});
const saved = await store.load(session.activeId());
assert.equal(saved.turns[1].cards.length, 1);
assert.equal(saved.turns[1].cards[0].conversation_id, saved.id);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_ensure_active_creates_an_empty_scoped_memory_home_without_loading_history() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as store from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await store.clearAll();
const loaded = [];
const session = mountConversationSession({chat:{loadHistory:turns => loaded.push(turns)},store});
const first = await session.ensureActive();
assert.equal(session.activeId(), first.id);
assert.deepEqual(first.turns, []);
assert.equal(loaded.length, 0);
assert.equal((await session.ensureActive()).id, first.id);
await store.updateScoped(first.id, scoped => [...scoped, {id:'memory-1',scope:'conversation'}]);
await session.refreshActive();
assert.equal(session.activeRecord().scoped.length, 1);
await session.startNew();
assert.deepEqual(loaded.at(-1), []);
const next = await session.ensureActive();
assert.notEqual(next.id, first.id);
assert.deepEqual(next.scoped, []);
assert.deepEqual(loaded.at(-1), []);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_delete_during_queued_save_still_clears_the_active_chat() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as realStore from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await realStore.clearAll();
let release;
const gate = new Promise(resolve => { release = resolve; });
let block = false;
const store = {...realStore, saveTurn: async (...args) => {
  if (block) await gate;
  return realStore.saveTurn(...args);
}};
const loaded = [], status = {textContent:''};
const session = mountConversationSession({chat:{loadHistory:turns => loaded.push(turns)},
  root:{querySelector:() => status},store});
await session.keepTurn({role:'user',content:'İlk soru'});
const deletedId = session.activeId();
block = true;
const pending = session.keepTurn({role:'assistant',content:'Bekleyen yanıt'});
await realStore.remove(deletedId);
const clearing = session.onDeleted(deletedId);
release();
await Promise.all([pending,clearing]);
assert.equal(session.activeId(), null);
assert.deepEqual(loaded.at(-1), []);
assert.equal(status.textContent, 'Açık sohbet silindi. Yeni sohbet başladı.');
await session.keepTurn({role:'user',content:'Sonraki soru'});
assert.notEqual(session.activeId(), deletedId);
"""
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_session_serializes_delete_and_clear_with_pending_turns() -> None:
    run_node(
        """
import assert from 'node:assert/strict';
import * as realStore from './src/nabiz/console/static/js/conversations.js';
import {mountConversationSession} from './src/nabiz/console/static/js/conversation_session.js';
await realStore.clearAll();
let release;
let gate = new Promise(resolve => { release = resolve; });
let block = false;
const store = {...realStore, saveTurn: async (...args) => {
  if (block) await gate;
  return realStore.saveTurn(...args);
}};
const loaded = [];
const session = mountConversationSession({chat:{loadHistory:turns => loaded.push(turns)},store});
await session.keepTurn({role:'user',content:'İlk soru'});
const first = session.activeId();
block = true;
const pending = session.keepTurn({role:'assistant',content:'Bekleyen yanıt'});
const deleting = session.deleteConversation(first);
release();
assert.equal((await deleting).id, first);
await pending;
assert.equal(session.activeId(), null);
assert.equal(await realStore.load(first), null);
assert.deepEqual(loaded.at(-1), []);
block = false;
await session.keepTurn({role:'user',content:'Yeni soru'});
const second = session.activeId();
gate = new Promise(resolve => { release = resolve; });
block = true;
const pendingAgain = session.keepTurn({role:'assistant',content:'İkinci bekleyen yanıt'});
const clearing = session.clearConversations();
release();
assert.equal(await clearing, true);
await pendingAgain;
assert.equal(session.activeId(), null);
assert.deepEqual(await realStore.list(), []);
assert.deepEqual(loaded.at(-1), []);
assert.notEqual(second, first);
"""
    )


def test_catalog_has_matching_key_sets() -> None:
    assert set(CATALOG["tr"]) == set(CATALOG["en"])
    assert json.dumps(CATALOG, ensure_ascii=False)
