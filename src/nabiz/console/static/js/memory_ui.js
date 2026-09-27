/* The account's memory editor. Labels stay in this browser; only the chosen need key may be sent. */
import { list as listConversations } from './conversations.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { INTERESTS } from './memory_store.js';
import { NEEDS } from './profile.js';

const TYPES = ['interest', 'place', 'need', 'health'];
const COPY = {
  intro: 'Bu tarayıcıdaki hafıza: yalnız onayladığınız bilgiler burada hatırlanır. Başka cihazda ya da tarayıcıda görünmez; hesabınıza bağlı değildir.',
  empty: 'Henüz hatırlanan bir şey yok. Sohbette onayladıklarınız burada görünür.',
  add: 'Kendim ekle', edit: 'Düzelt', forget: 'Unut', save: 'Kaydet', cancel: 'Vazgeç',
  all: 'Tümünü unut', label: 'Hatırlanacak bilgi', type: 'Tür', key: 'Seçiminiz',
  profile: 'Sonraki sohbetlerde', conversation: 'Yalnız bu sohbette',
  scope: 'Hatırlama süresi', need: 'Rotalarda şöyle kullan', none: 'Rotalarda kullanma',
  health: 'Bu bilgi yalnız bu tarayıcıda durur. Sunucuya, operatöre ve takvime gitmez. Teşhis değildir.',
  forgot: 'Unutuldu. Eski sohbet metni silinmez.', saved: 'Hafıza kaydedildi.',
  updated: 'Hafıza düzeltildi.', cleared: 'Hafızadaki kayıtlar unutuldu.',
  failed: 'Hafıza değiştirilemedi. Yeniden deneyin.',
  chooseScope: 'Bu bilginin ne kadar süre hatırlanacağını seçin.',
  noConversation: 'Bu sohbet artık açık değil. Yeni bir sohbet başlatıp yeniden deneyin.',
  source_chat_suggestion: 'Sohbette onayladınız', source_user_typed: 'Kendiniz eklediniz',
  source_profile_form: 'Profilimden eklendi', source_migrated_v1: 'Önceki hafızadan taşındı',
  profileNeeds: "Profilim'de seçtiğiniz ihtiyaçlar da kullanılır: {names}.", profileLink: "Profilim'e git",
  interests: 'İlgilerim', places: 'Sık yerlerim', needs: 'İhtiyaçlarım', healths: 'Sağlık beyanlarım',
  interest: 'İlgi', place: 'Sık yer', needType: 'İhtiyaç', healthType: 'Sağlık beyanı',
  scoped: 'Yalnız şu sohbette: {title}',
  demo: 'Örnek kişiyi yükle', demoLabel: 'Örnek kişi: gerçek veri değil.',
  demoLoaded: 'Örnek kişi yüklendi. Gerçek veri kullanılmadı.',
};
const LEGACY_STATUS_TEXT = Object.freeze({ memory_cleared: 'Hafıza temizlendi.', item_deleted: 'Kayıt silindi.' });
const tx = (key, vars) => t(`ui.memory.${key}`, COPY[key], vars);
const TYPE_TITLES = { interest: 'interests', place: 'places', need: 'needs', health: 'healths' };
const TYPE_NAMES = { interest: 'interest', place: 'place', need: 'needType', health: 'healthType' };
const INTEREST_LABELS = {
  culture: 'Kültür ve sanat', museum: 'Müze', theatre: 'Tiyatro', concert: 'Konser', cinema: 'Sinema',
  library: 'Kütüphane', sport: 'Spor', nature: 'Doğa', children: 'Çocuk etkinlikleri', course: 'Kurs',
};

function element(doc, tag, className = '', value = '') {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}

function select(doc, name, options, selected, label) {
  const wrap = element(doc, 'label', 'memory-field');
  wrap.append(element(doc, 'span', '', label));
  const input = element(doc, 'select');
  input.name = name;
  options.forEach(([value, text]) => {
    const option = element(doc, 'option', '', text);
    option.value = value;
    option.selected = value === selected;
    input.append(option);
  });
  wrap.append(input);
  return wrap;
}

function scopeFields(doc, selected, name) {
  const field = element(doc, 'fieldset', 'memory-scope');
  field.append(element(doc, 'legend', '', tx('scope')));
  for (const [value, key] of [['conversation', 'conversation'], ['profile', 'profile']]) {
    const label = element(doc, 'label', 'memory-choice');
    const input = element(doc, 'input');
    input.type = 'radio'; input.name = name; input.value = value; input.checked = value === selected;
    label.append(input, element(doc, 'span', '', tx(key)));
    field.append(label);
  }
  return field;
}

function recordForm(doc, record = null) {
  const form = element(doc, 'form', 'memory-form');
  form.dataset.mode = record ? 'edit' : 'add';
  if (record) form.dataset.id = record.id;
  if (!record) form.append(select(doc, 'type', TYPES.map((type) => [type, tx(TYPE_NAMES[type])]), 'interest', tx('type')));
  const labelWrap = element(doc, 'label', 'memory-field');
  labelWrap.append(element(doc, 'span', '', tx('label')));
  const label = element(doc, 'input');
  label.type = 'text'; label.name = 'label'; label.required = true; label.maxLength = 160;
  label.value = record?.label || '';
  labelWrap.append(label); form.append(labelWrap);
  const type = record?.type || 'interest';
  const options = type === 'need' ? NEEDS.map(({ key, label: name }) => [key, name])
    : Object.entries(INTEREST_LABELS).filter(([key]) => INTERESTS.includes(key));
  const keyWrap = select(doc, 'key', [['', tx('key')], ...options], record?.key || '', tx('key'));
  keyWrap.classList.add('memory-key-field');
  keyWrap.hidden = !['interest', 'need'].includes(type) || Boolean(record);
  form.append(keyWrap, scopeFields(doc, record?.scope || (type === 'health' ? '' : 'conversation'),
    record ? `scope-${record.id}` : 'scope-add'));
  const healthWrap = element(doc, 'div', 'memory-health-fields');
  healthWrap.append(select(doc, 'need_key', [['', tx('none')], ...NEEDS.map(({ key, label: name }) => [key, name])],
    record?.need_key || '', tx('need')));
  const details = element(doc, 'details', 'memory-health-note');
  details.append(element(doc, 'summary', '', tx('health')), element(doc, 'p', '', tx('health')));
  healthWrap.append(details); healthWrap.hidden = type !== 'health'; form.append(healthWrap);
  const actions = element(doc, 'div', 'memory-actions');
  const save = element(doc, 'button', 'btn', tx('save')); save.type = 'submit';
  const cancel = element(doc, 'button', 'btn btn-quiet', tx('cancel'));
  cancel.type = 'button'; cancel.dataset.cancel = 'true';
  actions.append(save, cancel); form.append(actions);
  return form;
}

function dateLabel(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(date);
}

function mountMemoryPanel(root, { store, session, getProfile = () => ({}), onChanged = () => {} }) {
  if (!root) throw new TypeError('Hafızam bölümü bulunamadı.');
  const doc = root.ownerDocument;
  const intro = element(doc, 'p', 'section-note', tx('intro'));
  const profileLine = element(doc, 'p', 'memory-profile-needs');
  const profileLink = element(doc, 'a', '', tx('profileLink')); profileLink.href = '#profilim';
  profileLine.append(profileLink);
  const list = element(doc, 'div', 'memory-groups'); list.id = 'memory-list';
  const empty = element(doc, 'p', 'memory-empty', tx('empty')); empty.id = 'memory-empty';
  const addButton = element(doc, 'button', 'btn btn-quiet', tx('add'));
  addButton.id = 'memory-add-toggle'; addButton.type = 'button';
  const addForm = recordForm(doc); addForm.id = 'memory-add-form'; addForm.hidden = true;
  const clearButton = element(doc, 'button', 'btn btn-quiet', tx('all'));
  clearButton.id = 'memory-clear'; clearButton.type = 'button'; clearButton.hidden = true;
  const status = element(doc, 'p', 'status-line');
  status.id = 'memory-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const shell = [...root.children].filter((node) => /^(summary|h[1-6]|details)$/i.test(node.tagName));
  const demo = new URLSearchParams(doc.defaultView?.location?.search || globalThis.location?.search || '')
    .get('demo') === '1';
  const demoButton = element(doc, 'button', 'btn btn-quiet', tx('demo'));
  demoButton.type = 'button'; demoButton.id = 'memory-demo';
  const demoLabel = element(doc, 'p', 'memory-demo-label', tx('demoLabel'));
  root.replaceChildren(...shell, intro, profileLine, list, empty, addButton, addForm,
    ...(demo ? [demoButton, demoLabel] : []), clearButton, status);
  let records = [];

  function row(record, titles) {
    const item = element(doc, 'li', 'memory-item'); item.dataset.id = record.id;
    const content = element(doc, 'div', 'memory-content');
    const value = element(doc, 'strong', 'memory-value', record.label); value.lang = record.lang || doc.documentElement.lang;
    const scope = record.scope === 'conversation'
      ? tx('scoped', { title: titles.get(record.conversation_id) || tx('conversation') }) : tx('profile');
    const source = tx(`source_${record.source || 'user_typed'}`);
    content.append(value, element(doc, 'span', 'memory-type', tx(TYPE_NAMES[record.type])),
      element(doc, 'span', 'memory-meta', scope),
      element(doc, 'span', 'memory-meta', `${source} · ${dateLabel(record.consent_at)}`));
    const actions = element(doc, 'div', 'memory-actions');
    for (const [action, key] of [['edit', 'edit'], ['forget', 'forget']]) {
      const button = element(doc, 'button', 'btn btn-quiet', tx(key));
      button.type = 'button'; button.dataset[action] = record.id; actions.append(button);
    }
    item.append(content, actions);
    return item;
  }

  async function refresh() {
    list.setAttribute('aria-busy', 'true');
    try {
      const [found, conversations] = await Promise.all([store.list({}), listConversations()]);
      records = found.filter((record) => TYPES.includes(record.type));
      const titles = new Map(conversations.map((record) => [record.id, record.title]));
      list.replaceChildren();
      for (const type of TYPES) {
        const group = records.filter((record) => record.type === type);
        if (!group.length) continue;
        const section = element(doc, 'section', 'memory-group');
        const heading = element(doc, 'h3', '', tx(TYPE_TITLES[type]));
        const items = element(doc, 'ul', 'memory-list');
        group.forEach((record) => items.append(row(record, titles)));
        section.append(heading, items); list.append(section);
      }
      empty.hidden = records.length > 0; clearButton.hidden = records.length === 0;
      const profile = getProfile() || {};
      const names = profile.consent ? (profile.needs || []).map((key) => NEEDS.find((need) => need.key === key)?.label)
        .filter(Boolean) : [];
      profileLine.hidden = names.length === 0;
      profileLine.textContent = `${tx('profileNeeds', { names: names.join(', ') })} `;
      profileLine.append(profileLink);
    } catch {
      status.textContent = tx('failed');
    } finally {
      list.removeAttribute('aria-busy');
    }
  }

  root.addEventListener('change', (event) => {
    if (event.target.name !== 'type' || !addForm.contains(event.target)) return;
    const type = event.target.value;
    addForm.querySelector('.memory-key-field').hidden = !['interest', 'need'].includes(type);
    addForm.querySelector('.memory-health-fields').hidden = type !== 'health';
    const key = addForm.querySelector('[name="key"]');
    const options = type === 'need' ? NEEDS.map(({ key: value, label }) => [value, label])
      : Object.entries(INTEREST_LABELS).filter(([value]) => INTERESTS.includes(value));
    key.replaceChildren();
    for (const [value, text] of [['', tx('key')], ...options]) {
      const option = element(doc, 'option', '', text); option.value = value; key.append(option);
    }
    if (type === 'health') addForm.querySelectorAll('[name="scope-add"]').forEach((radio) => { radio.checked = false; });
  });

  root.addEventListener('click', async (event) => {
    const target = event.target.closest('button');
    if (!target) return;
    if (target === addButton) { addForm.hidden = false; addForm.querySelector('[name="label"]').focus(); return; }
    if (target.dataset.cancel) {
      if (target.closest('form') === addForm) { addForm.hidden = true; addButton.focus(); }
      else { await refresh(); list.querySelector('button[data-edit]')?.focus(); }
      return;
    }
    if (target.dataset.edit) {
      const record = records.find((entry) => entry.id === target.dataset.edit);
      const item = target.closest('.memory-item');
      if (record && item) { item.replaceChildren(recordForm(doc, record)); item.querySelector('[name="label"]').focus(); }
      return;
    }
    if (target.dataset.forget) {
      const items = [...list.querySelectorAll('.memory-item')];
      const index = items.indexOf(target.closest('.memory-item'));
      try {
        if (!await store.forget(target.dataset.forget)) throw new Error('Memory was not forgotten');
        await session.refreshActive?.(); await onChanged();
        await refresh(); status.textContent = tx('forgot');
        const after = [...list.querySelectorAll('.memory-item')];
        (after[Math.min(index, after.length - 1)]?.querySelector('button') || addButton).focus();
      } catch { status.textContent = tx('failed'); }
      return;
    }
    if (target === clearButton) {
      try { if (!await store.forgetAll()) throw new Error('Memory was not cleared');
        await session.refreshActive?.(); await onChanged(); await refresh();
        status.textContent = tx('cleared'); addButton.focus(); }
      catch { status.textContent = tx('failed'); }
    }
    if (target === demoButton && demo) {
      try {
        for (const [type, key, label] of [
          ['need', 'slow_walk', 'Uzun yürümek istemiyorum'],
          ['interest', 'culture', 'Kültür ve sanat'],
          ['need', 'step_free', 'Merdivensiz ulaşım tercih ediyorum'],
        ]) {
          if (!records.some((record) => record.scope === 'profile' && record.type === type && record.key === key)) {
            if (!await store.add({ type, key, label, scope: 'profile', conversation_id: null,
              source: 'profile_form', sensitive: false, related_ids: [] })) throw new Error('Demo could not be saved');
          }
        }
        await onChanged(); await refresh(); status.textContent = tx('demoLoaded'); demoButton.focus();
      } catch { status.textContent = tx('failed'); }
    }
  });

  root.addEventListener('submit', async (event) => {
    const form = event.target.closest('form.memory-form');
    if (!form || !root.contains(form)) return;
    event.preventDefault();
    const old = form.dataset.mode === 'edit' ? records.find((record) => record.id === form.dataset.id) : null;
    const type = old?.type || form.querySelector('[name="type"]').value;
    const scope = [...form.querySelectorAll('input[type="radio"]')].find((radio) => radio.checked)?.value;
    if (!scope) { status.textContent = tx('chooseScope'); form.querySelector('input[type="radio"]')?.focus(); return; }
    const label = form.querySelector('[name="label"]').value.trim();
    const key = old?.key || (['need', 'interest'].includes(type) ? form.querySelector('[name="key"]').value : null);
    if (!label || (['need', 'interest'].includes(type) && !key)) { form.querySelector('[name="label"]').focus(); return; }
    try {
      if (scope === 'conversation' && !session.activeId()) await session.ensureActive();
      const conversationId = scope === 'conversation' ? session.activeId() : null;
      if (scope === 'conversation' && !conversationId) { status.textContent = tx('noConversation'); return; }
      const patch = { label, scope, conversation_id: conversationId,
        need_key: type === 'health' ? form.querySelector('[name="need_key"]').value || null : null };
      const saved = old ? await store.update(old.id, patch)
        : await store.add({ ...patch, type, key, source: 'user_typed', sensitive: type === 'health', related_ids: [] });
      if (!saved) throw new Error('Memory was not saved');
      await session.refreshActive?.(); await onChanged();
      addForm.hidden = true; addForm.reset(); await refresh();
      status.textContent = tx(old ? 'updated' : 'saved'); addButton.focus();
    } catch { status.textContent = tx('failed'); }
  });
  onLang(() => { intro.textContent = tx('intro'); empty.textContent = tx('empty'); addButton.textContent = tx('add');
    clearButton.textContent = tx('all'); profileLink.textContent = tx('profileLink');
    demoButton.textContent = tx('demo'); demoLabel.textContent = tx('demoLabel');
    void refresh(); });
  void refresh();
  return { refresh };
}

export { mountMemoryPanel, LEGACY_STATUS_TEXT };
