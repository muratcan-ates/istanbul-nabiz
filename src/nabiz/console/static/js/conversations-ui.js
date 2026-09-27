import { clearAll, expiresAt, linkedCounts, list, load, purgeOlderThan, removeWithScoped, storageStatus } from './conversations.js';
import { currentLang, onLang, t } from './i18n_text.js';

const PRIVACY_TEXT = 'Sohbetleriniz yalnız bu tarayıcıda, oluşturulduktan sonra 30 gün saklanır. Sunucuya kaydedilmez.';
const EMPTY_TEXT = 'Henüz sohbet yok. Yeni sohbet başlatarak soru sorabilirsiniz.';
const COPY = {
  title: 'Sohbetlerim', new: 'Yeni sohbet', toggle: 'Geçmiş', clear: 'Tüm sohbetleri sil',
  delete: 'Sohbeti sil', unavailable: 'Bu tarayıcı geçmişi saklamıyor. Sonraki ziyaretinizde sohbet görünmeyebilir.',
  privacy: PRIVACY_TEXT, empty: EMPTY_TEXT, delete_label: '{title} sohbetini sil',
  expires: '{date} tarihinde silinecek', trimmed: 'En eski {count} mesaj silindi (sohbet başına 80 mesaj).',
  delete_title: 'Sohbeti sil', delete_body: 'Bu sohbetin mesajları ve kartları bu tarayıcıdan silinir.',
  delete_all_body: 'Tüm sohbetlerin mesajları ve kartları bu tarayıcıdan silinir.',
  delete_linked_memory: 'Bu sohbette eklenen {count} hafıza kaydı ayrıca duruyor.',
  also_forget: 'Bunları da unut', linked_plans: 'Bağlı {count} takvim ya da bildirim kaydı silinmez; kendi bölümünden yönetilir.',
  cancel: 'Vazgeç', confirm: 'Evet, sohbeti sil', confirm_all: 'Evet, sohbetleri sil',
  deleted: 'Sohbet silindi.', cleared: 'Tüm sohbetler silindi.', active_deleted: 'Açık sohbet silindi. Yeni sohbet başladı.',
  scoped_gone: '{count} yalnız bu sohbetteki hafıza kaydı silindi.',
  linked_kept: '{count} bağlı plan ya da bildirim kaydı kaldı.',
  memory_kept: '{count} sonraki sohbet hafıza kaydı kaldı.',
  memory_forgotten: '{count} sonraki sohbet hafıza kaydı unutuldu.',
  memory_failed: '{count} hafıza kaydı unutulamadı; Hafızam bölümünden yeniden deneyin.',
  other_memory_kept: 'Diğer {count} hafıza kaydı Hafızam bölümünde kaldı.',
  delete_error: 'Sohbet silinemedi. Yeniden deneyin.',
};
// Keep the existing dyn.convo_* Turkish source values until the shared catalog is migrated.
const LEGACY_COPY = Object.freeze({
  clear: 'Hepsini sil',
  privacy: 'Sohbetleriniz yalnız bu cihazda, 30 gün saklanır. Sunucuya kaydedilmez.',
  empty: 'Henüz sohbet yok. Sorduğunuz her şey yalnız bu cihazda saklanır.',
  delete_confirm: 'Bu sohbet bu cihazdan silinsin mi?',
  clear_confirm: 'Tüm sohbetler bu cihazdan silinsin mi?',
  compaction: 'Önceki mesajlar kısaltılarak gönderiliyor; yalnız son {count} soru hatırlanıyor.',
});
const convoText = (key, vars = {}) => t(`ui.history.${key}`, COPY[key], vars);

function dateLabel(value, withTime = true) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const options = withTime
    ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
    : { day: '2-digit', month: '2-digit' };
  return new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', options).format(date);
}

function node(doc, tag, className, value) {
  const element = doc.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

function mountConversations({ root, onOpen = () => {}, onNew = () => {}, onDelete = removeWithScoped,
  onClearAll = clearAll, activeId = () => null, memoryStore = null }) {
  if (!root) throw new TypeError('Sohbet listesi için bir kök öğe gerekir.');
  const doc = root.ownerDocument;
  root.classList.add('convo-root');
  root.innerHTML = '<div class="convo-bar"><button type="button" class="convo-new btn">Yeni sohbet</button>'
    + '<button type="button" class="convo-toggle btn-quiet" aria-expanded="false" aria-controls="convo-panel">Geçmiş</button></div>'
    + '<section class="convo-panel" id="convo-panel" aria-labelledby="convo-heading" hidden>'
    + '<div class="convo-header"><h2 class="convo-heading" id="convo-heading">Sohbetlerim</h2>'
    + '<button type="button" class="convo-clear btn-quiet">Tüm sohbetleri sil</button></div>'
    + '<ul class="convo-list"></ul><p class="convo-empty" hidden></p>'
    + '<p class="convo-unavailable" hidden></p><p class="convo-privacy"></p></section>'
    + '<p class="convo-status" role="status" aria-live="polite"></p><dialog class="convo-dialog"></dialog>';
  const panel = root.querySelector('.convo-panel');
  const rows = root.querySelector('.convo-list');
  const statusLine = root.querySelector('.convo-status');
  const dialog = root.querySelector('.convo-dialog');
  let returnFocus = null;
  dialog.addEventListener('close', () => { returnFocus?.focus(); returnFocus = null; });

  function announce(message) { statusLine.textContent = message; }

  function translate() {
    root.setAttribute('aria-label', convoText('title'));
    root.querySelector('.convo-new').textContent = convoText('new');
    root.querySelector('.convo-toggle').textContent = convoText('toggle');
    root.querySelector('.convo-heading').textContent = convoText('title');
    root.querySelector('.convo-clear').textContent = convoText('clear');
    root.querySelector('.convo-empty').textContent = convoText('empty');
    root.querySelector('.convo-unavailable').textContent = convoText('unavailable');
    root.querySelector('.convo-privacy').textContent = convoText('privacy');
    rows.querySelectorAll('.convo-item').forEach((item) => {
      const title = item.querySelector('.convo-title');
      if (title.dataset.defaultTitle === 'true') title.textContent = convoText('new');
      const date = item.querySelector('.convo-date');
      date.textContent = dateLabel(date.dateTime);
      item.querySelector('.convo-expires').textContent = convoText('expires', {
        date: dateLabel(item.querySelector('.convo-expires').dateTime, false),
      });
      const trimmed = item.querySelector('.convo-note');
      if (trimmed) trimmed.textContent = convoText('trimmed', { count: Number(trimmed.dataset.count) });
      const deleteButton = item.querySelector('.convo-delete');
      deleteButton.textContent = convoText('delete');
      deleteButton.setAttribute('aria-label', convoText('delete_label', { title: title.textContent }));
    });
  }

  async function render() {
    const conversations = await list();
    const storage = await storageStatus();
    root.querySelector('.convo-unavailable').hidden = storage.persistent;
    rows.replaceChildren();
    root.querySelector('.convo-empty').hidden = conversations.length > 0;
    root.querySelector('.convo-clear').hidden = conversations.length === 0;
    for (const conversation of conversations) {
      const item = node(doc, 'li', 'convo-item');
      item.dataset.id = conversation.id;
      const openButton = node(doc, 'button', 'convo-open');
      openButton.type = 'button';
      const title = node(doc, 'span', 'convo-title', conversation.title || convoText('new'));
      title.dataset.defaultTitle = String(!conversation.title || (conversation.title === 'Yeni sohbet'
        && !conversation.turns.some((turn) => turn.role === 'user' && !turn.redacted)));
      const date = node(doc, 'time', 'convo-date');
      date.dateTime = conversation.updatedAt || '';
      const expiry = node(doc, 'time', 'convo-expires');
      expiry.dateTime = expiresAt(conversation);
      openButton.append(title, date);
      item.append(openButton, expiry);
      if (conversation.trimmed > 0) {
        const note = node(doc, 'p', 'convo-note');
        note.dataset.count = String(conversation.trimmed);
        item.append(note);
      }
      const deleteButton = node(doc, 'button', 'convo-delete btn-quiet');
      deleteButton.type = 'button';
      item.append(deleteButton);
      rows.append(item);
    }
    translate();
  }

  function modal(elements, trigger) {
    returnFocus = trigger;
    dialog.replaceChildren(...elements);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.hidden = false;
    dialog.querySelector('button')?.focus();
  }

  async function confirmDelete(id, trigger, all = false) {
    const conversation = all ? null : await load(id);
    if (!all && !conversation) { await render(); return; }
    const wasActive = !all && activeId() === id;
    const targets = all ? await list() : [conversation];
    const targetIds = new Set(targets.map((item) => item.id));
    const scopedCount = targets.reduce((sum, item) => sum + (item.scoped?.length || 0), 0);
    const linkedTotal = targets.reduce((sum, item) => sum + linkedCounts(item).total, 0);
    const profileMemory = memoryStore ? await memoryStore.list({ scope: 'profile' }) : [];
    const related = profileMemory.filter((item) => item.related_ids?.some((relatedId) => targetIds.has(relatedId)));
    const otherMemoryCount = profileMemory.length - related.length;
    const heading = node(doc, 'h2', 'convo-dialog-title', convoText('delete_title'));
    const body = node(doc, 'p', 'convo-dialog-body', convoText(all ? 'delete_all_body' : 'delete_body'));
    const contents = [heading, body];
    if (related.length) {
      contents.push(node(doc, 'p', 'convo-dialog-memory', convoText('delete_linked_memory', { count: related.length })));
      const label = node(doc, 'label', 'convo-also-label');
      const check = node(doc, 'input');
      check.type = 'checkbox'; check.className = 'convo-also-forget';
      label.append(check, node(doc, 'span', '', convoText('also_forget')));
      contents.push(label);
    }
    if (linkedTotal) contents.push(node(doc, 'p', 'convo-dialog-linked', convoText('linked_plans', { count: linkedTotal })));
    const actions = node(doc, 'div', 'convo-dialog-actions');
    const cancel = node(doc, 'button', 'convo-cancel btn-quiet', convoText('cancel'));
    cancel.type = 'button';
    const accept = node(doc, 'button', 'convo-confirm btn btn-danger', convoText(all ? 'confirm_all' : 'confirm'));
    accept.type = 'button';
    const error = node(doc, 'p', 'convo-dialog-error');
    error.setAttribute('role', 'status');
    actions.append(cancel, accept); contents.push(actions, error);
    modal(contents, trigger);
    cancel.addEventListener('click', () => dialog.close());
    accept.addEventListener('click', async () => {
      accept.disabled = true;
      try {
        const alsoForget = dialog.querySelector('.convo-also-forget')?.checked === true;
        let forgottenCount = 0;
        if (all) {
          if (!await onClearAll()) throw new Error('Conversation removal failed');
        }
        else {
          if (!await onDelete(id)) throw new Error('Conversation removal failed');
        }
        if (alsoForget) for (const item of related) {
          try { if (await memoryStore.forget(item.id)) forgottenCount += 1; } catch { /* Report what stayed. */ }
        }
        const parts = [convoText(all ? 'cleared' : wasActive ? 'active_deleted' : 'deleted')];
        if (scopedCount) parts.push(convoText('scoped_gone', { count: scopedCount }));
        if (forgottenCount) parts.push(convoText('memory_forgotten', { count: forgottenCount }));
        if (related.length > forgottenCount) parts.push(convoText(alsoForget ? 'memory_failed' : 'memory_kept',
          { count: related.length - forgottenCount }));
        if (otherMemoryCount) parts.push(convoText('other_memory_kept', { count: otherMemoryCount }));
        if (linkedTotal) parts.push(convoText('linked_kept', { count: linkedTotal }));
        returnFocus = null;
        dialog.close();
        await render();
        announce(parts.join(' '));
        const first = rows.querySelector('.convo-open') || root.querySelector('.convo-new');
        first.focus();
      } catch {
        accept.disabled = false;
        error.textContent = convoText('delete_error');
      }
    });
  }

  root.addEventListener('click', async (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target) || dialog.contains(target)) return;
    if (target.matches('.convo-toggle')) {
      panel.hidden = !panel.hidden;
      target.setAttribute('aria-expanded', String(!panel.hidden));
    } else if (target.matches('.convo-new')) {
      await onNew();
      announce('');
      await render();
    } else if (target.matches('.convo-clear')) {
      await confirmDelete(null, target, true);
    } else {
      const item = target.closest('.convo-item');
      if (!item) return;
      if (target.matches('.convo-delete')) await confirmDelete(item.dataset.id, target);
      else if (target.matches('.convo-open')) {
        const conversation = await load(item.dataset.id);
        if (conversation) await onOpen(conversation);
      }
    }
  });
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Delete' || event.target.closest('input, textarea, select')) return;
    const item = event.target.closest('.convo-item');
    if (!item) return;
    event.preventDefault();
    void confirmDelete(item.dataset.id, item.querySelector('.convo-delete'));
  });
  onLang(translate);
  translate();
  const ready = purgeOlderThan(30).then(render);
  return { ready, refresh: render, open: (id) => load(id), announce };
}

export { mountConversations, PRIVACY_TEXT, EMPTY_TEXT, LEGACY_COPY };
