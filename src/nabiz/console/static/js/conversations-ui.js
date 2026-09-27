import {
  compactionNote, list, load, newConversation, purgeOlderThan, remove, storageStatus, clearAll,
} from './conversations.js';
import { HISTORY_TURNS } from './config.js';
import { currentLang, onLang, t } from './i18n_text.js';

const PRIVACY_TEXT = 'Sohbetleriniz yalnız bu cihazda, 30 gün saklanır. Sunucuya kaydedilmez.';
const EMPTY_TEXT = 'Henüz sohbet yok. Sorduğunuz her şey yalnız bu cihazda saklanır.';
const CONVO_TEXT = {
  title: 'Sohbetlerim', new: 'Yeni sohbet', clear: 'Hepsini sil', delete: 'Sil',
  unavailable: 'Bu tarayıcı geçmişi saklamıyor.', privacy: PRIVACY_TEXT, empty: EMPTY_TEXT,
  delete_label: '{title} sohbetini sil', delete_confirm: 'Bu sohbet bu cihazdan silinsin mi?',
  clear_confirm: 'Tüm sohbetler bu cihazdan silinsin mi?', deleted: 'Sohbet silindi', cleared: 'Tüm sohbetler silindi',
  compaction: 'Önceki mesajlar kısaltılarak gönderiliyor; yalnız son {count} soru hatırlanıyor.',
};
const convoText = (key, vars = {}) => t(`dyn.convo_${key}`, CONVO_TEXT[key], vars);

function dateLabel(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
}

function translateLabels(root) {
  root.setAttribute('aria-label', convoText('title'));
  root.querySelectorAll('[data-convo-text]').forEach((node) => {
    node.textContent = convoText(node.dataset.convoText, { count: HISTORY_TURNS });
  });
  root.querySelectorAll('.convo-date').forEach((node) => { node.textContent = dateLabel(node.dateTime); });
  root.querySelectorAll('.convo-item').forEach((item) => {
    item.querySelector('.convo-delete').setAttribute('aria-label', convoText('delete_label', {
      title: item.querySelector('.convo-title').textContent,
    }));
  });
}

function mountConversations({ root, onOpen = () => {}, onNew = () => {} }) {
  if (!root) throw new TypeError('Sohbet listesi için bir kök öğe gerekir.');
  const document = root.ownerDocument;
  root.classList.add('convo-root');
  root.innerHTML = '<button type="button" class="convo-toggle" aria-expanded="false" aria-controls="convo-panel" data-convo-text="title">Sohbetlerim</button>'
    + '<section class="convo-panel" id="convo-panel" aria-labelledby="convo-heading" hidden>'
    + '<div class="convo-header"><h2 class="convo-heading" id="convo-heading" data-convo-text="title">Sohbetlerim</h2>'
    + '<div class="convo-actions"><button type="button" class="convo-new" data-convo-text="new">Yeni sohbet</button>'
    + '<button type="button" class="convo-clear" data-convo-text="clear">Hepsini sil</button></div></div>'
    + '<ul class="convo-list"></ul><p class="convo-empty" data-convo-text="empty" hidden></p>'
    + '<p class="convo-unavailable" data-convo-text="unavailable" hidden>Bu tarayıcı geçmişi saklamıyor.</p>'
    + `<p class="convo-privacy" data-convo-text="privacy">${PRIVACY_TEXT}</p></section>`
    + '<p class="convo-status" role="status" aria-live="polite"></p>';
  const panel = root.querySelector('.convo-panel');
  const listElement = root.querySelector('.convo-list');
  const emptyElement = root.querySelector('.convo-empty');
  const statusElement = root.querySelector('.convo-status');
  function announce(key) {
    statusElement.dataset.convoText = key;
    statusElement.textContent = convoText(key);
  }
  translateLabels(root);
  onLang(() => translateLabels(root));

  async function render() {
    const conversations = await list();
    const status = await storageStatus();
    root.querySelector('.convo-unavailable').hidden = status.persistent;
    listElement.replaceChildren();
    emptyElement.hidden = conversations.length > 0;
    emptyElement.textContent = convoText('empty');
    root.querySelector('.convo-clear').disabled = conversations.length === 0;
    conversations.forEach((conversation) => {
      const item = document.createElement('li');
      item.className = 'convo-item';
      item.dataset.id = conversation.id;
      const openButton = document.createElement('button');
      openButton.type = 'button';
      openButton.className = 'convo-open';
      const title = document.createElement('span');
      title.className = 'convo-title';
      const defaultTitle = !conversation.title || (conversation.title === 'Yeni sohbet'
        && !conversation.turns.some((turn) => turn.role === 'user'));
      if (defaultTitle) title.dataset.convoText = 'new';
      title.textContent = defaultTitle ? convoText('new') : conversation.title;
      const date = document.createElement('time');
      date.className = 'convo-date';
      date.dateTime = conversation.updatedAt || '';
      date.textContent = dateLabel(conversation.updatedAt);
      openButton.append(title, date);
      item.appendChild(openButton);
      const noteText = compactionNote(conversation.turns.length, HISTORY_TURNS);
      if (noteText) {
        const note = document.createElement('p');
        note.className = 'convo-note';
        note.dataset.convoText = 'compaction';
        note.textContent = convoText('compaction', { count: HISTORY_TURNS });
        item.appendChild(note);
      }
      const deleteButton = document.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'convo-delete';
      deleteButton.dataset.convoText = 'delete';
      deleteButton.textContent = convoText('delete');
      deleteButton.setAttribute('aria-label', convoText('delete_label', { title: title.textContent }));
      item.appendChild(deleteButton);
      listElement.appendChild(item);
    });
    translateLabels(root);
  }

  async function createChat() {
    const conversation = await newConversation();
    statusElement.textContent = '';
    delete statusElement.dataset.convoText;
    await render();
    await onNew(conversation);
  }

  async function deleteChat(id) {
    const item = [...listElement.children].find((row) => row.dataset.id === id);
    const index = item ? [...listElement.children].indexOf(item) : 0;
    const confirm = document.defaultView?.confirm;
    if (!confirm || !confirm.call(document.defaultView, convoText('delete_confirm'))) return;
    await remove(id);
    announce('deleted');
    await render();
    const buttons = listElement.querySelectorAll('.convo-open');
    (buttons[Math.min(index, buttons.length - 1)] || root.querySelector('.convo-new')).focus();
  }

  root.addEventListener('click', async (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target)) return;
    if (target.matches('.convo-toggle')) {
      panel.hidden = !panel.hidden;
      target.setAttribute('aria-expanded', String(!panel.hidden));
    } else if (target.matches('.convo-new')) {
      await createChat();
    } else if (target.matches('.convo-clear')) {
      const confirm = document.defaultView?.confirm;
      if (confirm && confirm.call(document.defaultView, convoText('clear_confirm'))) {
        await clearAll();
        announce('cleared');
        await render();
        root.querySelector('.convo-new').focus();
      }
    } else {
      const item = target.closest('.convo-item');
      if (!item) return;
      if (target.matches('.convo-delete')) {
        await deleteChat(item.dataset.id);
      } else if (target.matches('.convo-open')) {
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
    void deleteChat(item.dataset.id);
  });

  const ready = purgeOlderThan(30).then(render);
  return { ready, refresh: render, open: (id) => load(id) };
}

export { mountConversations, PRIVACY_TEXT, EMPTY_TEXT };
