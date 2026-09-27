"""On-device memory boundaries, scope, migration and legacy profile contracts."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from conftest import REPO_ROOT


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_memory_store_scopes_consent_forgetting_and_share_boundaries() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore, INTERESTS, NEED_KEYS} from './src/nabiz/console/static/js/memory_store.js';

let instant = new Date('2026-09-27T11:00:00.000Z');
const saved = new Map();
const storage = {
  getItem: key => saved.get(key) ?? null,
  setItem: (key, value) => saved.set(key, value),
  removeItem: key => saved.delete(key),
};
const records = new Map([
  ['A', {id:'A', title:'Sohbet A', scoped:[]}],
  ['B', {id:'B', title:'Sohbet B', scoped:[]}],
]);
const conversations = {
  load: async id => records.get(id) || null,
  list: async () => [...records.values()],
  updateScoped: async (id, updater) => {
    const record = records.get(id);
    if (!record) return null;
    const scoped = updater(record.scoped);
    records.set(id, {...record, scoped});
    return records.get(id);
  },
};
const memory = createMemoryStore({storage, now: () => instant, conversations});
assert.ok(INTERESTS.includes('culture'));
assert.ok(NEED_KEYS.has('slow_walk'));
assert.deepEqual(await memory.list({scope:'profile'}), []);
assert.deepEqual(memory.requestNeeds({profile:{consent:false, needs:[]}}), []);

const need = await memory.add({type:'need',key:'slow_walk',label:'Yavaş yürüyorum',scope:'profile',
  source:'chat_suggestion',consent_at:instant.toISOString()});
const interest = await memory.add({type:'interest',key:'culture',label:'Kültür ve sanat',scope:'profile',
  source:'chat_suggestion',consent_at:instant.toISOString()});
assert.ok(need?.id && interest?.id);
assert.equal(memory.listProfile().length, 2);
assert.deepEqual(memory.requestNeeds({profile:{consent:false,needs:[]}}), []);
assert.deepEqual(memory.requestNeeds({profile:{consent:true,needs:[]}}), ['slow_walk']);
assert.equal(await memory.add({type:'interest',key:'not-allowed',label:'Bilinmeyen',scope:'profile'}), null);

const health = await memory.add({type:'health',label:'Kalp rahatsızlığım var (örnek)',key:'ignored',
  scope:'profile',need_key:'step_free',sensitive:false,source:'user_typed'});
assert.equal(health.key, null);
assert.equal(health.sensitive, true);
const safeKeys = memory.requestNeeds({profile:{consent:true,needs:[]}});
assert.deepEqual(safeKeys, ['slow_walk','step_free']);
assert.equal(JSON.stringify(memory.shareable('model',{profile:{consent:true,needs:[]}})).includes('Kalp'), false);
for (const purpose of ['operator','calendar','outlook']) assert.deepEqual(memory.shareable(purpose), []);

const scoped = await memory.add({type:'health',label:'Diz ameliyatı sonrası dönemdeyim (örnek)',
  scope:'conversation',conversation_id:'A',source:'user_typed',need_key:'hearing'});
assert.ok(scoped?.id);
assert.equal((await memory.list({scope:'conversation',conversationId:'A'})).length, 1);
assert.deepEqual(memory.requestNeeds({profile:{consent:false,needs:[]},conversation:records.get('A')}), ['hearing']);
assert.deepEqual(memory.requestNeeds({profile:{consent:false,needs:[]},conversation:records.get('B')}), []);

const moved = await memory.update(need.id, {scope:'conversation',conversation_id:'A',label:'Kısa yürüyüş'});
assert.equal(moved.id, need.id);
assert.equal(moved.label, 'Kısa yürüyüş');
assert.equal(memory.listProfile().some(item => item.id === need.id), false);
assert.equal(records.get('A').scoped.some(item => item.id === need.id), true);
const back = await memory.update(need.id, {scope:'profile',conversation_id:null});
assert.equal(back.scope, 'profile');
assert.equal(records.get('A').scoped.some(item => item.id === need.id), false);
assert.equal(memory.listProfile().some(item => item.id === need.id), true);

await memory.forget(need.id);
assert.equal(memory.isForgotten('need','slow_walk'), true);
assert.equal(memory.requestNeeds({profile:{consent:true,needs:[]}}).includes('slow_walk'), false);
assert.equal((await memory.list()).some(item => item.id === need.id), false);
assert.equal((await memory.list({scope:'conversation',conversationId:'A'})).length, 1);
saved.set('nabiz.memory.v1', JSON.stringify([{key:'slow_walk',label:'Eski öneri'}]));
memory.migrateV1();
assert.equal(memory.listProfile().some(item => item.key === 'slow_walk'), false);
instant = new Date('2026-10-28T11:00:00.000Z');
assert.equal(memory.isForgotten('need','slow_walk'), false);

assert.equal(await memory.forgetAll(), true);
assert.deepEqual(await memory.list(), []);
assert.deepEqual(records.get('A').scoped, []);
assert.deepEqual(records.get('B').scoped, []);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_v1_migration_and_profile_compatibility() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';

const saved = new Map();
const storage = {
  getItem: key => saved.get(key) ?? null,
  setItem: (key, value) => saved.set(key, value),
  removeItem: key => saved.delete(key),
};
globalThis.localStorage = storage;
globalThis.window = {localStorage: storage};
saved.set('nabiz.memory.v1', JSON.stringify([
  {key:'slow_walk',label:'Yavaş yürüyorum',added_at:'2026-09-20T00:00:00.000Z'},
  {key:'station:Kadıköy',label:'Kadıköy',added_at:'2026-09-21T00:00:00.000Z'},
]));
const memory = createMemoryStore({storage, now: () => new Date('2026-09-27T00:00:00.000Z'),
  conversations:{list:async()=>[],load:async()=>null,updateScoped:async()=>null}});
assert.equal(memory.migrateV1(), 2);
assert.equal(saved.has('nabiz.memory.v1'), false);
assert.equal(memory.migrateV1(), 0);
assert.equal(memory.listProfile().length, 2);
assert.ok(memory.listProfile().every(item => item.source === 'migrated_v1'));
assert.ok(memory.listProfile().every(item => item.owner === 'browser'));  // 27 Eyl: browser memory

const profile = await import('./src/nabiz/console/static/js/profile.js');
assert.deepEqual(profile.readMemory(), [
  {key:'slow_walk',label:'Yavaş yürüyorum',added_at:'2026-09-20T00:00:00.000Z'},
  {key:'station:Kadıköy',label:'Kadıköy',added_at:'2026-09-21T00:00:00.000Z'},
]);
assert.deepEqual(profile.savedPlaces({stations:[],lines:[]},profile.readMemory()),
  {stations:['Kadıköy'],lines:[]});
assert.deepEqual(profile.effectiveNeeds({consent:false,needs:['step_free']},profile.readMemory()),[]);
assert.deepEqual(profile.effectiveNeeds({consent:true,needs:['step_free']},profile.readMemory()),
  ['step_free','slow_walk']);
assert.equal(profile.addMemory({key:'stroller',label:'Bebek arabası'}).length, 3);
assert.deepEqual(profile.removeMemory('stroller').map(item=>item.key),['slow_walk','station:Kadıköy']);
assert.equal(memory.isForgotten('need','stroller'), true);
profile.clearMemory();
assert.deepEqual(profile.readMemory(),[]);
assert.equal(saved.has('nabiz.memory.v1'), false);
assert.equal(profile.answerLanguage(profile.setAnswerLanguage({needs:[]},'en')),'en');
assert.equal(profile.profileReview({saved_at:'2026-08-01T00:00:00.000Z'},
  '2026-09-01T00:00:00.000Z').due,true);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_scoped_memory_is_owned_by_the_real_conversation_record() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {clearAll, load, newConversation, remove} from './src/nabiz/console/static/js/conversations.js';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';

await clearAll();
const storage = {getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const memory = createMemoryStore({storage});
const conversation = await newConversation();
const added = await memory.add({type:'need',key:'slow_walk',label:'Yavaş yürüyorum',
  scope:'conversation',conversation_id:conversation.id,source:'chat_suggestion'});
assert.ok(added?.id);
assert.equal((await load(conversation.id)).scoped[0].id, added.id);
assert.deepEqual(memory.requestNeeds({profile:{consent:false,needs:[]},
  conversation:await load(conversation.id)}), ['slow_walk']);
await remove(conversation.id);
assert.equal(await load(conversation.id), null);
assert.deepEqual(await memory.list({scope:'conversation'}), []);
await clearAll();
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_failed_scope_moves_do_not_report_success_or_leave_a_profile_copy() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
let rejectWrite = false;
const records = new Map([['A',{id:'A',scoped:[]}]]);
const conversations = {
  load:async id => records.get(id) || null,
  list:async () => [...records.values()],
  updateScoped:async (id,updater) => {
    if (rejectWrite) return null;
    const record = records.get(id);
    if (!record) return null;
    const next = {...record,scoped:updater(record.scoped)};
    records.set(id,next);
    return next;
  },
};
const memory = createMemoryStore({storage,conversations});
const profile = await memory.add({type:'need',key:'slow_walk',label:'Yavaş yürüyorum',scope:'profile'});
rejectWrite = true;
assert.equal(await memory.update(profile.id,{scope:'conversation',conversation_id:'A'}),null);
assert.equal(memory.listProfile().some(item => item.id === profile.id),true);
assert.deepEqual(records.get('A').scoped,[]);
rejectWrite = false;
const scoped = await memory.add({type:'need',key:'step_free',label:'Adımsız',
  scope:'conversation',conversation_id:'A'});
rejectWrite = true;
assert.equal(await memory.update(scoped.id,{scope:'profile',conversation_id:null}),null);
assert.equal(memory.listProfile().some(item => item.id === scoped.id),false);
assert.equal(records.get('A').scoped.some(item => item.id === scoped.id),true);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
