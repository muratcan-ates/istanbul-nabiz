"""Device-only memory surfaces and the three explicit deletion paths."""

from __future__ import annotations

import json

from test_static_a11y import STATIC, node_json

CATALOG = {
    "tr": {
        "ui.history.title": "Sohbetlerim", "ui.history.clear": "Tüm sohbetleri sil",
        "ui.history.delete": "Sohbeti sil",
        "ui.history.unavailable": "Bu tarayıcı geçmişi saklamıyor. Sonraki ziyaretinizde sohbet görünmeyebilir.",
        "ui.history.privacy": "Sohbetleriniz yalnız bu tarayıcıda, oluşturulduktan sonra 30 gün saklanır. Sunucuya kaydedilmez.",
        "ui.history.empty": "Henüz sohbet yok. Yeni sohbet başlatarak soru sorabilirsiniz.",
        "ui.history.delete_label": "{title} sohbetini sil",
        "ui.history.new": "Yeni sohbet", "ui.history.toggle": "Geçmiş",
        "ui.history.expires": "{date} tarihinde silinecek",
        "ui.history.trimmed": "En eski {count} mesaj silindi (sohbet başına 80 mesaj).",
        "ui.history.active_deleted": "Açık sohbet silindi. Yeni sohbet başladı.",
        "ui.history.delete_title": "Sohbeti sil",
        "ui.history.delete_body": "Bu sohbetin mesajları ve kartları bu tarayıcıdan silinir.",
        "ui.history.delete_all_body": "Tüm sohbetlerin mesajları ve kartları bu tarayıcıdan silinir.",
        "ui.history.delete_linked_memory": "Bu sohbette eklenen {count} hafıza kaydı ayrıca duruyor.",
        "ui.history.also_forget": "Bunları da unut",
        "ui.history.linked_plans": "Bağlı {count} takvim ya da bildirim kaydı silinmez; kendi bölümünden yönetilir.",
        "ui.history.cancel": "Vazgeç", "ui.history.confirm": "Evet, sohbeti sil",
        "ui.history.confirm_all": "Evet, sohbetleri sil",
        "ui.history.deleted": "Sohbet silindi.", "ui.history.cleared": "Tüm sohbetler silindi.",
        "ui.history.scoped_gone": "{count} yalnız bu sohbetteki hafıza kaydı silindi.",
        "ui.history.linked_kept": "{count} bağlı plan ya da bildirim kaydı kaldı.",
        "ui.history.memory_kept": "{count} sonraki sohbet hafıza kaydı kaldı.",
        "ui.history.memory_forgotten": "{count} sonraki sohbet hafıza kaydı unutuldu.",
        "ui.history.memory_failed": "{count} hafıza kaydı unutulamadı; Hafızam bölümünden yeniden deneyin.",
        "ui.history.other_memory_kept": "Diğer {count} hafıza kaydı Hafızam bölümünde kaldı.",
        "ui.history.delete_error": "Sohbet silinemedi. Yeniden deneyin.",
        "ui.history.masked_emergency": "[acil yönlendirme]",
        "ui.history.masked_sensitive": "[hassas bilgi saklanmadı]",
        "ui.memory.intro": (
            "Bu tarayıcıdaki hafıza: yalnız onayladığınız bilgiler burada hatırlanır. "
            "Başka cihazda ya da tarayıcıda görünmez; hesabınıza bağlı değildir."
        ),
        "ui.memory.empty": "Henüz hatırlanan bir şey yok. Sohbette onayladıklarınız burada görünür.",
        "ui.memory.add": "Kendim ekle", "ui.memory.edit": "Düzelt", "ui.memory.forget": "Unut",
        "ui.memory.save": "Kaydet", "ui.memory.cancel": "Vazgeç", "ui.memory.all": "Tümünü unut",
        "ui.memory.label": "Hatırlanacak bilgi", "ui.memory.type": "Tür", "ui.memory.key": "Seçiminiz",
        "ui.memory.profile": "Sonraki sohbetlerde", "ui.memory.conversation": "Yalnız bu sohbette",
        "ui.memory.scope": "Hatırlama süresi", "ui.memory.need": "Rotalarda şöyle kullan",
        "ui.memory.none": "Rotalarda kullanma",
        "ui.memory.health": "Bu bilgi yalnız bu tarayıcıda durur. Sunucuya, operatöre ve takvime gitmez. Teşhis değildir.",
        "ui.memory.forgot": "Unutuldu. Eski sohbet metni silinmez.",
        "ui.memory.saved": "Hafıza kaydedildi.", "ui.memory.updated": "Hafıza düzeltildi.",
        "ui.memory.cleared": "Hafızadaki kayıtlar unutuldu.",
        "ui.memory.failed": "Hafıza değiştirilemedi. Yeniden deneyin.",
        "ui.memory.chooseScope": "Bu bilginin ne kadar süre hatırlanacağını seçin.",
        "ui.memory.noConversation": "Bu sohbet artık açık değil. Yeni bir sohbet başlatıp yeniden deneyin.",
        "ui.memory.source_chat_suggestion": "Sohbette onayladınız",
        "ui.memory.source_user_typed": "Kendiniz eklediniz",
        "ui.memory.source_profile_form": "Profilimden eklendi",
        "ui.memory.source_migrated_v1": "Önceki hafızadan taşındı",
        "ui.memory.profileNeeds": "Profilim'de seçtiğiniz ihtiyaçlar da kullanılır: {names}.",
        "ui.memory.profileLink": "Profilim'e git",
        "ui.memory.interests": "İlgilerim", "ui.memory.places": "Sık yerlerim",
        "ui.memory.needs": "İhtiyaçlarım", "ui.memory.healths": "Sağlık beyanlarım",
        "ui.memory.interest": "İlgi", "ui.memory.place": "Sık yer",
        "ui.memory.needType": "İhtiyaç", "ui.memory.healthType": "Sağlık beyanı",
        "ui.memory.scoped": "Yalnız şu sohbette: {title}",
        "ui.memory.demo": "Örnek kişiyi yükle", "ui.memory.demoLabel": "Örnek kişi: gerçek veri değil.",
        "ui.memory.demoLoaded": "Örnek kişi yüklendi. Gerçek veri kullanılmadı.",
        "ui.memory.title": "Hatırlayayım mı?", "ui.memory.choose": "Hatırlamamı istediğiniz satırları seçin.",
        "ui.memory.here": "Yalnız bu sohbette", "ui.memory.always": "Sonraki sohbetlerde de hatırla",
        "ui.memory.remember": "Hatırla", "ui.memory.no": "Hayır",
        "ui.memory.expired": "Bu öneri artık geçerli değil.",
        "ui.memory.cardSaved": "Seçtiğiniz bilgiler Hafızam bölümüne eklendi.",
        "ui.memory.cardFailed": "Kaydedilemedi. Yeniden deneyin.",
        "ui.reset.title": "Tüm Nabız verimi sil", "ui.reset.confirm": "Evet, hepsini sil",
        "ui.reset.cancel": "Vazgeç",
        "ui.reset.description": "Bu tarayıcıdaki seçili veri grupları silinir. Bu işlem geri alınamaz.",
        "ui.reset.external": "Bilgisayarınıza indirilen takvim dosyaları ve Outlook'a eklenmiş kayıtlar buradan silinemez.",
        "ui.reset.deleted": "silindi", "ui.reset.failed": "silinemedi",
        "ui.reset.reload": "Sayfayı yenile",
        "ui.reset.result": "Silme bitti. Her grubun sonucunu aşağıda görebilirsiniz.",
        "ui.reset.count": "{count} kayıt",
        "ui.reset.kept": "silinmedi, bu tarayıcıda kaldı",
        "ui.reset.retryAccount": "Hesap bölümünden yeniden deneyin.",
        "ui.reset.conversations": "Sohbetler", "ui.reset.memory": "Hafıza", "ui.reset.profile": "Profil",
        "ui.reset.follows": "Takip", "ui.reset.stops": "Kayıtlı duraklar",
        "ui.reset.reports": "Bildirimler", "ui.reset.requests": "Operatör talepleri",
        "ui.reset.cards": "Kaydedilen kartlar", "ui.reset.discovery": "Keşif tercihleri",
        "ui.reset.account": "Örnek hesap", "ui.reset.feedback": "Geri bildirim",
        "ui.reset.appearance": "Görünüm ve dil",
    },
    "en": {
        "ui.history.title": "My chats", "ui.history.clear": "Delete all chats",
        "ui.history.delete": "Delete chat",
        "ui.history.unavailable": "This browser cannot save chat history. Your chats may not appear on your next visit.",
        "ui.history.privacy": "Your chats stay in this browser for 30 days from creation. They are not saved on the server.",
        "ui.history.empty": "No chats yet. Start a new chat to ask a question.",
        "ui.history.delete_label": "Delete the {title} chat",
        "ui.history.new": "New chat", "ui.history.toggle": "History",
        "ui.history.expires": "Will be deleted on {date}",
        "ui.history.trimmed": "The oldest {count} messages were deleted (80 messages per chat).",
        "ui.history.active_deleted": "The open chat was deleted. A new chat has started.",
        "ui.history.delete_title": "Delete chat",
        "ui.history.delete_body": "This chat's messages and cards will be deleted from this browser.",
        "ui.history.delete_all_body": "All chats' messages and cards will be deleted from this browser.",
        "ui.history.delete_linked_memory": "{count} memory items added in this chat remain separately.",
        "ui.history.also_forget": "Forget these too",
        "ui.history.linked_plans": "{count} linked calendar or report items remain; manage them in their sections.",
        "ui.history.cancel": "Cancel", "ui.history.confirm": "Yes, delete chat",
        "ui.history.confirm_all": "Yes, delete chats",
        "ui.history.deleted": "Chat deleted.", "ui.history.cleared": "All chats deleted.",
        "ui.history.scoped_gone": "{count} items remembered only in this chat were deleted.",
        "ui.history.linked_kept": "{count} linked plan or report items remain.",
        "ui.history.memory_kept": "{count} items remembered in later chats remain.",
        "ui.history.memory_forgotten": "{count} items remembered in later chats were forgotten.",
        "ui.history.memory_failed": "{count} memory items could not be forgotten. Please try again in Memory.",
        "ui.history.other_memory_kept": "Another {count} memory items remain in Memory.",
        "ui.history.delete_error": "The chat could not be deleted. Please try again.",
        "ui.history.masked_emergency": "[emergency guidance]",
        "ui.history.masked_sensitive": "[sensitive information not saved]",
        "ui.memory.intro": (
            "Memory in this browser: only information you approve is remembered here. "
            "It does not appear on other devices or browsers and is not linked to your account."
        ),
        "ui.memory.empty": "Nothing is remembered yet. Items you approve in a chat will appear here.",
        "ui.memory.add": "Add myself", "ui.memory.edit": "Edit", "ui.memory.forget": "Forget",
        "ui.memory.save": "Save", "ui.memory.cancel": "Cancel", "ui.memory.all": "Forget all",
        "ui.memory.label": "Information to remember", "ui.memory.type": "Type", "ui.memory.key": "Your choice",
        "ui.memory.profile": "In later chats", "ui.memory.conversation": "In this chat only",
        "ui.memory.scope": "How long to remember", "ui.memory.need": "Use for routes as",
        "ui.memory.none": "Do not use for routes",
        "ui.memory.health": (
            "This information stays in this browser. It is not sent to the server, "
            "an operator or a calendar. It is not a diagnosis."
        ),
        "ui.memory.forgot": "Forgotten. The old chat text remains.",
        "ui.memory.saved": "Memory saved.", "ui.memory.updated": "Memory updated.",
        "ui.memory.cleared": "Memory items forgotten.",
        "ui.memory.failed": "Memory could not be changed. Please try again.",
        "ui.memory.chooseScope": "Choose how long this information should be remembered.",
        "ui.memory.noConversation": "This chat is no longer open. Start a new chat and try again.",
        "ui.memory.source_chat_suggestion": "You approved this in a chat",
        "ui.memory.source_user_typed": "You added this",
        "ui.memory.source_profile_form": "Added from your profile",
        "ui.memory.source_migrated_v1": "Moved from earlier memory",
        "ui.memory.profileNeeds": "Your selected profile needs are also used: {names}.",
        "ui.memory.profileLink": "Go to my profile",
        "ui.memory.interests": "My interests", "ui.memory.places": "My frequent places",
        "ui.memory.needs": "My needs", "ui.memory.healths": "My health statements",
        "ui.memory.interest": "Interest", "ui.memory.place": "Frequent place",
        "ui.memory.needType": "Need", "ui.memory.healthType": "Health statement",
        "ui.memory.scoped": "In this chat only: {title}",
        "ui.memory.demo": "Load example person", "ui.memory.demoLabel": "Example person: no real data.",
        "ui.memory.demoLoaded": "Example person loaded. No real data was used.",
        "ui.memory.title": "Should I remember this?", "ui.memory.choose": "Select the items you want me to remember.",
        "ui.memory.here": "In this chat only", "ui.memory.always": "Remember in later chats too",
        "ui.memory.remember": "Remember", "ui.memory.no": "No",
        "ui.memory.expired": "This suggestion is no longer available.",
        "ui.memory.cardSaved": "Your selected items were added to Memory.",
        "ui.memory.cardFailed": "Could not save. Please try again.",
        "ui.reset.title": "Delete all my Nabız data", "ui.reset.confirm": "Yes, delete it all",
        "ui.reset.cancel": "Cancel",
        "ui.reset.description": "Selected data groups in this browser will be deleted. This cannot be undone.",
        "ui.reset.external": "Downloaded calendar files and events added to Outlook cannot be deleted here.",
        "ui.reset.deleted": "deleted", "ui.reset.failed": "could not be deleted",
        "ui.reset.reload": "Reload page",
        "ui.reset.result": "Deletion is complete. Review each group's result below.",
        "ui.reset.count": "{count} records",
        "ui.reset.kept": "not deleted, remains in this browser",
        "ui.reset.retryAccount": "Try again from the Account section.",
        "ui.reset.conversations": "Chats", "ui.reset.memory": "Memory", "ui.reset.profile": "Profile",
        "ui.reset.follows": "Follows", "ui.reset.stops": "Saved stops",
        "ui.reset.reports": "Reports", "ui.reset.requests": "Operator requests",
        "ui.reset.cards": "Saved cards", "ui.reset.discovery": "Discovery preferences",
        "ui.reset.account": "Example account", "ui.reset.feedback": "Feedback",
        "ui.reset.appearance": "Appearance and language",
    },
}


DOM = r"""
class Node {
  constructor(tag = 'div', doc = null) {
    this.tagName = tag; this.ownerDocument = doc || this; this.parentElement = null; this.children = [];
    this.listeners = {}; this.dataset = {}; this.attrs = {}; this.className = ''; this.id = '';
    this.hidden = false; this.checked = false; this.value = ''; this.name = ''; this.type = '';
    this._text = ''; this.open = false;
    this.classList = {add: (...names) => {
      this.className = [...new Set([...this.className.split(' '), ...names])].join(' ').trim();
    },
      contains: name => this.className.split(' ').includes(name)};
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value);
    this.children.forEach(child => child.parentElement = null); this.children = []; }
  get firstChild() { return this.children[0] || null; }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentElement = this; this.children.push(node); } }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) { this.children.forEach(child => child.parentElement = null);
    this.children = []; this._text = ''; this.append(...nodes); }
  remove() { if (this.parentElement) { const list = this.parentElement.children;
    list.splice(list.indexOf(this), 1); this.parentElement = null; } }
  replaceWith(node) { if (!this.parentElement) return; const parent = this.parentElement;
    const index = parent.children.indexOf(this); node.remove(); parent.children[index] = node;
    node.parentElement = parent; this.parentElement = null; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  matches(selector) {
    const checked = selector.endsWith(':checked'); if (checked) selector = selector.slice(0, -8);
    const attr = selector.match(/\[([\w-]+)(?:="([^"]*)")?\]/); if (attr) selector = selector.replace(attr[0], '');
    const [tag, ...classes] = selector.split('.');
    if (tag.startsWith('#')) { if (this.id !== tag.slice(1)) return false; }
    else if (tag && tag !== '*' && this.tagName !== tag) return false;
    if (!classes.every(name => this.classList.contains(name))) return false;
    const dataName = attr?.[1].startsWith('data-') ? attr[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()) : null;
    if (attr && (attr[2] === undefined ? !(attr[1] in this || (dataName && dataName in this.dataset))
      : String(this[attr[1]] ?? this.dataset[dataName] ?? '') !== attr[2])) return false;
    return !checked || this.checked;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll(selector)])
    .filter(node => node.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  dispatchEvent(event) { event.target ||= this; for (const callback of this.listeners[event.type] || []) callback(event);
    if (!event.stopped) this.parentElement?.dispatchEvent(event); }
  focus() { this.ownerDocument.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(evt('close', this)); }
  reset() { this.querySelectorAll('input').forEach(input => { input.value = ''; input.checked = false; }); }
}
function evt(type, target, detail = null) { return {type, target, detail, preventDefault() { this.prevented = true; },
  stopPropagation() { this.stopped = true; }}; }
function setup() {
  const doc = new Node('document'); doc.documentElement = {lang: 'tr'}; doc.ownerDocument = doc;
  doc.createElement = tag => new Node(tag, doc); doc.defaultView = {location: {reload() { doc.reloaded = true; }}};
  const root = doc.createElement('section'); root.id = 'hafizam'; doc.append(root);
  const account = doc.createElement('section'); account.id = 'hesabim'; doc.append(account);
  const values = new Map(); const storage = {getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key),
    key: index => [...values.keys()][index], get length() { return values.size; }};
  globalThis.document = doc; globalThis.localStorage = storage;
  globalThis.window = {localStorage: storage, addEventListener() {}, removeEventListener() {}};
  return {doc, root, account, storage, values};
}
const click = node => node.dispatchEvent(evt('click', node));
const submit = node => node.dispatchEvent(evt('submit', node));
const change = node => node.dispatchEvent(evt('change', node));
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0));
  await new Promise(resolve => setTimeout(resolve, 0)); };
"""


def run_ui(tmp_path, modules: dict[str, str], body: str):
    return node_json(tmp_path, modules, f"{DOM}\n{body}")


def test_catalog_pairs_cover_all_memory_history_and_reset_text() -> None:
    assert CATALOG["tr"].keys() == CATALOG["en"].keys()
    for prefix in ("ui.memory.", "ui.history.", "ui.reset."):
        assert any(key.startswith(prefix) for key in CATALOG["tr"])
    for language in CATALOG.values():
        assert all(value and "—" not in value and "–" not in value for value in language.values())
    assert "Siz" not in CATALOG["tr"]["ui.memory.empty"]  # clear instruction, no filler honorific


def test_memory_panel_requires_scope_and_supports_add_edit_forget(tmp_path) -> None:
    out = run_ui(tmp_path, {
        "ui": "js/memory_ui.js", "memory": "js/memory_store.js",
        "conversations": "js/conversations.js", "i18n": "js/i18n_text.js",
    }, f"""
const s = setup(); i18n.setCatalogs('tr', {json.dumps(CATALOG['tr'], ensure_ascii=False)}, {{}});
const active = await conversations.newConversation();
let current = active; const session = {{activeId: () => current?.id || null,
  activeRecord: () => current, async startNew() {{ current = await conversations.newConversation(); }},
  async refreshActive() {{ current = await conversations.load(current.id); }} }};
const store = memory.createMemoryStore({{storage: s.storage, conversations}});
const panel = ui.mountMemoryPanel(s.root, {{store, session, getProfile: () => ({{consent: true, needs: ['step_free']}})}});
await settle(); const initiallyEmpty = !s.root.querySelector('#memory-empty').hidden;
click(s.root.querySelector('#memory-add-toggle'));
const add = s.root.querySelector('#memory-add-form');
add.querySelector('[name="type"]').value = 'health'; change(add.querySelector('[name="type"]'));
add.querySelector('[name="label"]').value = 'Örnek sağlık beyanı';
add.querySelector('[name="need_key"]').value = 'slow_walk'; submit(add); await settle();
const requiresScope = s.root.querySelector('#memory-status').textContent.includes('süre');
const scope = add.querySelectorAll('input[type="radio"]')[0]; scope.checked = true;
submit(add); await settle();
let saved = await store.list({{scope:'conversation', conversationId:active.id}});
const health = saved[0], grouped = s.root.querySelectorAll('.memory-group').length;
click(s.root.querySelector('button[data-edit]'));
const edit = s.root.querySelector('form.memory-form');
edit.querySelector('[name="label"]').value = 'Düzeltilmiş beyan';
const radios = edit.querySelectorAll('input[type="radio"]'); radios[0].checked = false; radios[1].checked = true;
submit(edit); await settle();
saved = await store.list({{scope:'profile'}});
const moved = saved.length === 1 && saved[0].label === 'Düzeltilmiş beyan';
click(s.root.querySelector('button[data-forget]')); await settle();
const forgotten = (await store.list({{}})).length === 0;
console.log(JSON.stringify({{ids: ['memory-list','memory-empty','memory-clear','memory-status']
  .every(id => !!s.root.querySelector('#'+id)),
  initiallyEmpty, requiresScope, healthType: health?.type, healthSensitive: health?.sensitive,
  needs: store.requestNeeds({{profile:{{consent:false,needs:[]}},conversation:await conversations.load(active.id)}}),
  grouped, moved, forgotten, status: s.root.querySelector('#memory-status').textContent,
  profileLink: s.root.querySelector('.memory-profile-needs').textContent.includes('Adımsız erişim')}}));
""")
    assert out == {
        "ids": True, "initiallyEmpty": True, "requiresScope": True,
        "healthType": "health", "healthSensitive": True, "needs": [],
        "grouped": 1, "moved": True, "forgotten": True,
        "status": CATALOG["tr"]["ui.memory.forgot"], "profileLink": True,
    }


def test_memory_card_is_unchecked_and_persists_only_confirmed_items(tmp_path) -> None:
    out = run_ui(tmp_path, {
        "card": "js/memory_card.js", "memory": "js/memory_store.js",
        "conversations": "js/conversations.js", "i18n": "js/i18n_text.js",
    }, f"""
const s = setup(); i18n.setCatalogs('tr', {json.dumps(CATALOG['tr'], ensure_ascii=False)}, {{}});
let current = await conversations.newConversation(); const store = memory.createMemoryStore({{storage:s.storage, conversations}});
const cardStatuses = [];
const session = {{activeId: () => current.id, async addCard(_messageId, value) {{
  cardStatuses.push(value.status); return {{card:value}}; }},
  async refreshActive() {{ current = await conversations.load(current.id); }}}};
const host = s.doc.createElement('div'); s.doc.append(host); const appended = [];
const registry = {{registerCardType(_type, render) {{ this.render = render; }},
  appendCard(target, value, ctx) {{ appended.push(value); target.append(this.render(value, {{...ctx, document:s.doc}})); }}}};
const mounted = card.mountMemorySuggestions({{store, session, registry, doc:s.doc}}); await mounted.ready;
s.doc.dispatchEvent(evt('nabiz:chat-final', s.doc, {{question:'Uzun yürümek istemiyorum, kültür etkinliklerini seviyorum',
  final:{{}}, host, messageId:'m1'}})); await settle();
const offer = host.querySelector('.memory-card'); const checks = offer.querySelectorAll('input[type="checkbox"]');
const before = (await store.list({{scope:'profile'}})).length;
const disabled = offer.querySelector('button[data-cardAction]').getAttribute('aria-disabled');
checks.forEach(input => input.checked = true); change(checks[0]);
const radios = offer.querySelectorAll('input[type="radio"]');
radios[0].checked = false; radios[1].checked = true; change(radios[1]);
const action = offer.querySelector('button[data-cardAction]').dataset.cardAction;
s.doc.dispatchEvent(evt('nabiz:card-action', s.doc, {{card_id:appended[0].id,type:'memory',action,
  conversation_id:current.id}})); await settle();
const saved = await store.list({{scope:'profile'}});
const restored = card.renderMemoryCard(appended[0], {{document:s.doc, restored:true}});
await store.forget(saved.find(item => item.key === 'slow_walk').id);
const forgottenServer = registry.render({{...appended[0],id:'forgotten-server',body:{{key:'slow_walk',label:'Yavaş yürüyorum'}}}},
  {{document:s.doc}});
s.doc.dispatchEvent(evt('nabiz:chat-final', s.doc, {{question:'Uzun yürümek istemiyorum, kültür etkinliklerini seviyorum',
  final:{{}}, host, messageId:'m2'}})); await settle();
console.log(JSON.stringify({{types:appended[0].body.items.map(item => item.key), before, disabled, action,
  saved:saved.map(item => item.key).sort(), restoredButtons:restored.querySelectorAll('button').length,
  afterForgetOffers:appended.length, forgottenServerButtons:forgottenServer.querySelectorAll('button').length,
  cardStatuses, needs:store.requestNeeds({{profile:{{consent:true,needs:[]}},conversation:null}}),
  actions:appended[0].actions.map(a => [a.id, a.kind, a.requires_consent, a.operation_id])}}));
""")
    assert out == {
        "types": ["slow_walk", "culture"], "before": 0, "disabled": "true",
        "action": "remember_always", "saved": ["culture", "slow_walk"],
        "restoredButtons": 0, "afterForgetOffers": 1, "forgottenServerButtons": 0,
        "cardStatuses": ["awaiting_confirmation", "done"], "needs": [],
        "actions": [["remember_here", "device", True, None], ["remember_always", "device", True, None]],
    }


def test_old_card_cannot_write_into_new_chat_and_decline_saves_nothing(tmp_path) -> None:
    body = """
const s = setup(); i18n.setCatalogs('tr', __CATALOG__, {});
let current = await conversations.newConversation(); const firstId = current.id;
const store = memory.createMemoryStore({storage:s.storage, conversations});
const session = {activeId: () => current.id, async addCard(_id, value) { return {card:value}; },
  async refreshActive() { current = await conversations.load(current.id); }};
const host = s.doc.createElement('div'); s.doc.append(host); const appended = [];
const registry = {registerCardType(_type, render) { this.render = render; },
  appendCard(target, value, ctx) { appended.push(value); target.append(this.render(value, {...ctx, document:s.doc})); }};
await card.mountMemorySuggestions({store, session, registry, doc:s.doc}).ready;
const serverCard = {v:1,id:'server-1',conversation_id:firstId,message_id:'a1',type:'memory',
  status:'awaiting_confirmation',title:'Hatırlayayım mı?',body:{key:'slow_walk',label:'Yavaş yürüyorum'},
  sources:[],source_time:'',linked_id:null,actions:['remember_here','remember_always'],sensitive:false};
host.append(card.renderMemoryCard(serverCard, {document:s.doc}));
s.doc.dispatchEvent(evt('nabiz:chat-final', s.doc, {question:'Uzun yürümek istemiyorum, kültür etkinliklerini seviyorum',
  final:{memory_suggestion:{key:'slow_walk',label:'Yavaş yürüyorum'}}, host, messageId:'a1'})); await settle();
const serverDeduped = host.querySelector('.memory-card').querySelectorAll('input[type="checkbox"]')
  .map(input => input.dataset.key);
const old = host.querySelector('.memory-card'); old.querySelector('input[type="checkbox"]').checked = true;
change(old.querySelector('input[type="checkbox"]'));
current = await conversations.newConversation();
s.doc.dispatchEvent(evt('nabiz:card-action', s.doc, {card_id:'server-1', type:'memory',
  action:'remember_here', conversation_id:firstId})); await settle();
const expired = old.textContent.includes('Bu öneri artık geçerli değil.');
s.doc.dispatchEvent(evt('nabiz:chat-final', s.doc, {question:'Kalp rahatsızlığım var, uzun yürümek istemiyorum',
  final:{}, host, messageId:'b1'})); await settle();
const afterHealth = host.querySelectorAll('.memory-card').length;
s.doc.dispatchEvent(evt('nabiz:chat-final', s.doc, {question:'Merdivensiz yol kullanıyorum',
  final:{}, host, messageId:'b2'})); await settle();
const newCard = host.querySelectorAll('.memory-card').at(-1);
click(newCard.querySelector('button[data-memoryDismiss]')); await settle();
console.log(JSON.stringify({serverDeduped, expired, afterHealth,
  declined:newCard.textContent.includes('Bu öneri artık geçerli değil.'),
  stored:(await store.list({})).length, offers:host.querySelectorAll('.memory-card').length}));
""".replace("__CATALOG__", json.dumps(CATALOG["tr"], ensure_ascii=False))
    out = run_ui(tmp_path, {
        "card": "js/memory_card.js", "memory": "js/memory_store.js",
        "conversations": "js/conversations.js", "i18n": "js/i18n_text.js",
    }, body)
    assert out == {
        "serverDeduped": ["slow_walk", "culture"], "expired": True, "afterHealth": 1,
        "declined": True, "stored": 0, "offers": 2,
    }


def test_demo_person_is_synthetic_and_loaded_once_only_on_demo_url(tmp_path) -> None:
    body = """
const s = setup(); s.doc.defaultView.location.search = '?demo=1';
i18n.setCatalogs('tr', __CATALOG__, {});
const store = memory.createMemoryStore({storage:s.storage, conversations});
const session = {activeId:() => null, refreshActive:async () => {}};
ui.mountMemoryPanel(s.root, {store, session, getProfile:() => ({consent:true,needs:[]})}); await settle();
const button = s.root.querySelector('#memory-demo'); click(button); await settle(); click(button); await settle();
const records = await store.list({scope:'profile'});
console.log(JSON.stringify({visible:!!button, label:s.root.querySelector('.memory-demo-label').textContent,
  entries:records.map(item => [item.type,item.key,item.sensitive]).sort(),
  needs:store.requestNeeds({profile:{consent:true,needs:[]},conversation:null}).sort()}));
""".replace("__CATALOG__", json.dumps(CATALOG["tr"], ensure_ascii=False))
    out = run_ui(tmp_path, {
        "ui": "js/memory_ui.js", "memory": "js/memory_store.js",
        "conversations": "js/conversations.js", "i18n": "js/i18n_text.js",
    }, body)
    assert out == {
        "visible": True, "label": CATALOG["tr"]["ui.memory.demoLabel"],
        "entries": [["interest", "culture", False], ["need", "slow_walk", False], ["need", "step_free", False]],
        "needs": ["slow_walk", "step_free"],
    }


def test_reset_dialog_lists_groups_and_keeps_appearance_until_checked(tmp_path) -> None:
    out = run_ui(tmp_path, {"reset": "js/data_reset.js", "i18n": "js/i18n_text.js"}, f"""
const s = setup(); i18n.setCatalogs('tr', {json.dumps(CATALOG['tr'], ensure_ascii=False)}, {{}});
s.storage.setItem('nabiz.profile.v1', '{{"consent":true}}');
s.storage.setItem('nabiz-theme', 'dark'); s.storage.setItem('unrelated', 'keep');
let cleared = 0; const memory = {{list:async () => [], forgetAll:async () => true}};
const conversations = {{list:async () => [], clearAll:async () => {{cleared++; return true;}}}};
const resetView = reset.mountDataReset(s.account, {{store:memory, session:{{onClearedAll:async () => {{}}}},
  storage:s.storage, conversations}});
click(resetView.trigger); await settle();
const open = resetView.dialog.open, groups = resetView.dialog.querySelectorAll('.data-reset-group').length;
const optionalUnchecked = !resetView.dialog.querySelector('.data-reset-optional').querySelector('input')?.checked;
click(resetView.dialog.querySelectorAll('button').find(button => button.textContent === 'Evet, hepsini sil'));
await settle();
const first = {{profile:s.storage.getItem('nabiz.profile.v1'), theme:s.storage.getItem('nabiz-theme'),
  unrelated:s.storage.getItem('unrelated'), result:resetView.dialog.querySelector('.data-reset-status').textContent,
  external:resetView.dialog.querySelector('.data-reset-external').textContent}};
resetView.dialog.close(); click(resetView.trigger); await settle();
resetView.dialog.querySelector('.data-reset-optional').querySelector('input').checked = true;
click(resetView.dialog.querySelectorAll('button').find(button => button.textContent === 'Evet, hepsini sil'));
await settle();
console.log(JSON.stringify({{open, groups, optionalUnchecked, first, themeAfter:s.storage.getItem('nabiz-theme'),
  cleared, danger:resetView.trigger.className.includes('btn-danger'),
  resultGroups:resetView.dialog.querySelectorAll('.data-reset-group').length}}));
""")
    assert out["open"] and out["groups"] == 11 and out["optionalUnchecked"]
    assert out["first"] == {
        "profile": None, "theme": "dark", "unrelated": "keep",
        "result": CATALOG["tr"]["ui.reset.result"],
        "external": CATALOG["tr"]["ui.reset.external"],
    }
    assert out["themeAfter"] is None and out["cleared"] == 2
    assert out["danger"] and out["resultGroups"] == 12


def test_reset_reports_each_failed_storage_group(tmp_path) -> None:
    out = run_ui(tmp_path, {"reset": "js/data_reset.js"}, """
const s = setup(); const storage = {getItem:key => key === 'nabiz.profile.v1' ? 'present' : null,
  removeItem:key => { if (key === 'nabiz.profile.v1') throw new Error('blocked'); }};
const store = {forgetAll:async () => true};
const conversations = {list:async () => [], clearAll:async () => true};
const result = await reset.clearDataGroups({storage, store, conversations});
console.log(JSON.stringify({failed:result.filter(item => !item.deleted).map(item => item.id),
  optional:result.some(item => item.id === 'appearance'), total:result.length}));
""")
    assert out == {"failed": ["profile"], "optional": False, "total": 11}


def test_reset_preserves_account_token_on_server_failure_and_clears_brief_cache(tmp_path) -> None:
    out = run_ui(tmp_path, {"reset": "js/data_reset.js"}, """
const s = setup();
s.storage.setItem('nabiz.account.v1', JSON.stringify({token:'example-token'}));
s.storage.setItem('nabiz.device.v1', 'device');
s.storage.setItem('nabiz.follows.v1', '[{"id":"follow"}]');
s.storage.setItem('nabiz.profile.v1', '{"consent":true}');
const cached = new Set(['nabiz-brief-one','nabiz-brief-two','other-cache']);
const cacheStorage = {keys:async () => [...cached], delete:async key => cached.delete(key)};
const store = {forgetAll:async () => true};
const conversations = {list:async () => [], clearAll:async () => true};
let calls = 0;
const failed = await reset.clearDataGroups({storage:s.storage, store, conversations, cacheStorage,
  deleteAccount:async () => { calls++; const error = new Error('offline'); error.status = 0; throw error; }});
const first = {account:s.storage.getItem('nabiz.account.v1'), device:s.storage.getItem('nabiz.device.v1'),
  follow:s.storage.getItem('nabiz.follows.v1'), profile:s.storage.getItem('nabiz.profile.v1'),
  accountFailed:failed.find(item => item.id === 'account').remoteFailure,
  followFailed:!failed.find(item => item.id === 'follows').deleted,
  cache:[...cached].sort()};
const unauthorized = await reset.clearDataGroups({storage:s.storage, store, conversations, cacheStorage,
  deleteAccount:async () => { calls++; const error = new Error('already deleted'); error.status = 401; throw error; }});
console.log(JSON.stringify({first, calls, accountAfter:s.storage.getItem('nabiz.account.v1'),
  accountDeleted:unauthorized.find(item => item.id === 'account').deleted,
  accountFailed:unauthorized.find(item => item.id === 'account').remoteFailure}));
""")
    assert out["first"] == {
        "account": '{"token":"example-token"}', "device": "device",
        "follow": None, "profile": None, "accountFailed": True,
        "followFailed": True, "cache": ["other-cache"],
    }
    assert out["calls"] == 2 and out["accountAfter"] == '{"token":"example-token"}'
    assert not out["accountDeleted"] and out["accountFailed"]


def test_new_modules_fit_the_lane_and_use_the_registry_contract() -> None:
    for filename in ("memory_ui.js", "memory_card.js", "data_reset.js"):
        source = (STATIC / "js" / filename).read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 300
        assert "fetch(" not in source and "XMLHttpRequest" not in source
    card = (STATIC / "js" / "memory_card.js").read_text(encoding="utf-8")
    assert "import('./chat_cards.js')" in card
    assert "registerCardType?.('memory', renderWithForgotten)" in card
    assert "nabiz:chat-final" in card and "nabiz:card-action" in card
    css = (STATIC / "css" / "conversations.css").read_text(encoding="utf-8")
    assert len(css.splitlines()) <= 300 and "min-width: 0" in css and ".memory-card" in css
    assert not (STATIC / "css" / "memory.css").exists()  # 27 Eyl: memory rules live in conversations.css
    reset = (STATIC / "js" / "data_reset.js").read_text(encoding="utf-8")
    assert "retry.href = '#hesap'" in reset
