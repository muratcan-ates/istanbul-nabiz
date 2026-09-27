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
  scope:'profile',need_key:'step_free',sensitive:false,source:'user_typed',explicit_health_consent:true});
assert.equal(health.key, null);
assert.equal(health.sensitive, true);
const safeKeys = memory.requestNeeds({profile:{consent:true,needs:[]}});
assert.deepEqual(safeKeys, ['slow_walk','step_free']);
assert.equal(JSON.stringify(memory.shareable('model',{profile:{consent:true,needs:[]}})).includes('Kalp'), false);
for (const purpose of ['operator','calendar','outlook']) assert.deepEqual(memory.shareable(purpose), []);

const scoped = await memory.add({type:'health',label:'Diz ameliyatı sonrası dönemdeyim (örnek)',
  scope:'conversation',conversation_id:'A',source:'user_typed',need_key:'hearing',explicit_health_consent:true});
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_health_requires_separate_consent_and_existing_records_get_browser_owner() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
const conversations = {list:async()=>[conversation],load:async()=>conversation,
  updateScoped:async(id,updater)=>{conversation.scoped=updater(conversation.scoped);return conversation}};
const conversation = {id:'A',scoped:[{id:'old-scoped',type:'need',key:'step_free',label:'Adımsız',
  scope:'conversation',conversation_id:'A',source:'user_typed'}]};
const memory = createMemoryStore({storage,conversations});
for (const source of ['chat_suggestion','user_typed','profile_form']) {
  const rejected = await memory.add({type:'health',label:'Örnek sağlık beyanı',scope:'profile',source});
  assert.equal(rejected,null);
}
assert.equal(await memory.add({type:'health',label:'Örnek sağlık beyanı',scope:'profile',
  source:'chat_suggestion',explicit_health_consent:true}),null);
assert.equal(memory.addProfile({type:'health',label:'Örnek sağlık beyanı',source:'user_typed'}),null);
assert.equal(saved.has('nabiz.memory.v2'),false);
const accepted = await memory.add({type:'health',label:'Örnek sağlık beyanı',scope:'profile',
  source:'profile_form',explicit_health_consent:true,need_key:'slow_walk'});
assert.equal(accepted?.owner,'browser');
assert.equal('explicit_health_consent' in accepted,false);
assert.equal(JSON.parse(saved.get('nabiz.memory.v2'))[0].owner,'browser');
assert.equal(JSON.parse(saved.get('nabiz.memory.v2'))[0].explicit_health_consent,undefined);
const moved = await memory.update(accepted.id,{scope:'conversation',conversation_id:'A'});
assert.equal(moved?.id,accepted.id);
assert.equal(moved?.owner,'browser');
saved.set('nabiz.memory.v2',JSON.stringify([{id:'old-v2',type:'need',key:'slow_walk',
  label:'Yavaş yürüyorum',scope:'profile',source:'user_typed'}]));
assert.equal(memory.listProfile()[0].owner,'browser');
assert.equal(JSON.parse(saved.get('nabiz.memory.v2'))[0].owner,'browser');
assert.equal((await memory.list({scope:'conversation'}))[0].owner,'browser');
assert.equal(conversation.scoped[0].owner,'browser');
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_forgetting_keeps_matching_profile_selection_until_separate_removal() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
import {profileSelection,removeProfileSelection} from './src/nabiz/console/static/js/memory_forget.js';
import {readProfile,writeProfile} from './src/nabiz/console/static/js/profile.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
globalThis.localStorage = storage; globalThis.window = {localStorage:storage};
const memory = createMemoryStore({storage,conversations:{list:async()=>[],load:async()=>null}});
writeProfile({consent:true,needs:['slow_walk'],stations:['Kadıköy'],lines:['M4']});
const need = await memory.add({type:'need',key:'slow_walk',label:'Uzun yürümek istemiyorum',scope:'profile'});
assert.equal(profileSelection(need,readProfile()).label,'Yavaş yürüyorum');
assert.equal(profileSelection(need,{consent:false,needs:['slow_walk']}).active,false);
assert.equal(profileSelection(need,readProfile()).active,true);
await memory.forget(need.id);
assert.deepEqual(memory.requestNeeds({profile:readProfile()}),['slow_walk']);
assert.equal(memory.isForgotten('need','slow_walk'),true);
assert.equal(removeProfileSelection(need),true);
assert.equal(readProfile().needs.includes('slow_walk'),false);
assert.deepEqual(memory.requestNeeds({profile:readProfile()}),[]);
assert.equal(memory.isForgotten('need','slow_walk'),true);
const place = await memory.add({type:'place',key:'station:Kadıköy',label:'Kadıköy',scope:'profile'});
await memory.forget(place.id);
assert.equal(profileSelection(place,readProfile()).field,'stations');
assert.equal(removeProfileSelection(place),true);
assert.deepEqual(readProfile().stations,[]);
const line = await memory.add({type:'place',key:'line:M4',label:'M4',scope:'profile'});
await memory.forget(line.id);
assert.equal(removeProfileSelection(line),true);
assert.deepEqual(readProfile().lines,[]);
assert.equal(profileSelection(need,readProfile()),null);
assert.equal(removeProfileSelection(need),false);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_explicit_account_owner_is_neither_migrated_nor_exposed_or_deleted() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
const account = {id:'account-one',type:'need',key:'step_free',label:'Private account need',
  scope:'profile',source:'profile_form',owner:'account:A'};
const accountScoped = {id:'account-scoped',type:'need',key:'hearing',label:'Private scoped need',
  scope:'conversation',conversation_id:'A',source:'profile_form',owner:'account:A'};
const browserOld = {id:'browser-old',type:'need',key:'slow_walk',label:'Browser need',
  scope:'profile',source:'profile_form'};
const conversation = {id:'A',scoped:[accountScoped]};
const conversations = {list:async()=>[conversation],load:async()=>conversation,
  updateScoped:async(_id,updater)=>{conversation.scoped=updater(conversation.scoped);return conversation}};
saved.set('nabiz.memory.v2',JSON.stringify([account,browserOld]));
const memory = createMemoryStore({storage,conversations});
assert.deepEqual(memory.listProfile().map(item=>item.id),['browser-old']);
assert.deepEqual(JSON.parse(saved.get('nabiz.memory.v2')).map(item=>item.owner),['account:A','browser']);
assert.deepEqual((await memory.list()).map(item=>item.id),['browser-old']);
assert.equal(conversation.scoped[0].owner,'account:A');
assert.deepEqual(memory.requestNeeds({profile:{consent:true,needs:[]},conversation}),['slow_walk']);
await memory.add({type:'interest',key:'culture',label:'Kültür',scope:'profile'});
assert.equal(JSON.parse(saved.get('nabiz.memory.v2'))[0].owner,'account:A');
saved.set('nabiz.memory.v1',JSON.stringify([{key:'stroller',label:'Old browser item'}]));
assert.equal(memory.migrateV1(),1);
assert.equal(JSON.parse(saved.get('nabiz.memory.v2'))[0].owner,'account:A');
assert.equal(await memory.forgetAll(),true);
assert.deepEqual(await memory.list(),[]);
assert.deepEqual(JSON.parse(saved.get('nabiz.memory.v2')), [account]);
assert.deepEqual(conversation.scoped,[accountScoped]);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_forget_all_reports_partial_scoped_failure_and_marks_only_removed_items() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
const conversationsMap = new Map([['A',{id:'A',scoped:[]}],['B',{id:'B',scoped:[]}]]);
let failA = false;
const conversations = {list:async()=>[...conversationsMap.values()],
  load:async id=>conversationsMap.get(id), updateScoped:async(id,updater)=>{
    if (id === 'A' && failA) return null;
    const record = conversationsMap.get(id); record.scoped = updater(record.scoped); return record;
  }};
const memory = createMemoryStore({storage,conversations});
await memory.add({type:'need',key:'step_free',label:'Adımsız',scope:'profile'});
await memory.add({type:'need',key:'slow_walk',label:'Yavaş',scope:'conversation',conversation_id:'A'});
await memory.add({type:'need',key:'stroller',label:'Bebek arabası',scope:'conversation',conversation_id:'B'});
failA = true;
assert.equal(await memory.forgetAll(),false);
assert.deepEqual(memory.listProfile(),[]);
assert.equal(conversationsMap.get('A').scoped.length,1);
assert.deepEqual(conversationsMap.get('B').scoped,[]);
assert.equal(memory.isForgotten('need','step_free'),true);
assert.equal(memory.isForgotten('need','stroller'),true);
assert.equal(memory.isForgotten('need','slow_walk'),false);
assert.deepEqual(memory.requestNeeds({profile:{consent:false,needs:[]},
  conversation:conversationsMap.get('A')}),['slow_walk']);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_profile_removal_reports_other_memory_still_sending_the_same_need() -> None:
    script = r"""
import assert from 'node:assert/strict';
import {createMemoryStore} from './src/nabiz/console/static/js/memory_store.js';
import {createForgetActions} from './src/nabiz/console/static/js/memory_forget.js';
import {readProfile,writeProfile} from './src/nabiz/console/static/js/profile.js';
const saved = new Map();
const storage = {getItem:key => saved.get(key) ?? null,
  setItem:(key,value) => saved.set(key,value), removeItem:key => saved.delete(key)};
globalThis.localStorage = storage; globalThis.window = {localStorage:storage};
const store = createMemoryStore({storage,conversations:{list:async()=>[],load:async()=>null}});
writeProfile({consent:true,needs:['slow_walk'],stations:[],lines:[]});
const first = await store.add({type:'need',key:'slow_walk',label:'Yavaş yürüyorum',scope:'profile'});
await store.add({type:'need',key:'slow_walk',label:'Kısa yürüme',scope:'profile'});
const status = {textContent:''}, button = {hidden:true,focus(){}}, addButton = {focus(){}};
const actions = createForgetActions({store,session:{activeRecord:()=>null},onChanged:()=>{},
  refresh:()=>{},status,button,list:{querySelectorAll:()=>[]},addButton,tx:key=>key});
await actions.forget(first.id,null);
assert.equal(status.textContent,'forgot_profile_kept');
assert.equal(button.hidden,false);
await actions.removeFromProfile();
assert.equal(status.textContent,'removed_from_profile_still_used');
assert.equal(button.hidden,true);
assert.deepEqual(readProfile().needs,[]);
assert.deepEqual(store.requestNeeds({profile:readProfile()}),['slow_walk']);
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
