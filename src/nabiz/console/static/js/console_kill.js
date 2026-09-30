import { MOCK, get, post } from './api.js';
import { clock, esc } from './format.js';

const PAUSE_PATH = '/api/console/chat-pause';
const POLL_MS = 30000;

function sectionMarkup() {
  return `<section class="chat-pause" id="chat-pause" aria-labelledby="chat-pause-title">
    <div class="section-head"><h2 id="chat-pause-title">Vatandaş sohbeti</h2>
      <span class="section-note">Durdurma ve açma gerekçeyle deftere yazılır. Kartlar ve varış çalışmaya devam eder.</span></div>
    <button type="button" class="chat-pause-switch" id="chat-pause-switch" role="switch" aria-checked="true" aria-describedby="chat-pause-state">
      <span class="chat-pause-track" aria-hidden="true"></span><span class="chat-pause-label">Vatandaş sohbeti açık</span></button>
    <p class="status-line" id="chat-pause-state" role="status"></p>
  </section>`;
}

function dialogMarkup(paused) {
  const title = paused ? 'Vatandaş sohbetini yeniden aç' : 'Vatandaş sohbetini durdur';
  const description = paused
    ? 'Vatandaş sayfasındaki bant kalkar, soru kutusu yeniden açılır.'
    : "Vatandaş sayfası 'Sohbet geçici olarak durduruldu. 153'ü arayabilirsiniz.' bandını gösterir. Kartlar ve varış çalışmaya devam eder.";
  const action = paused ? 'Sohbeti aç' : 'Sohbeti durdur';
  const actionClass = paused ? 'btn btn-primary' : 'btn btn-danger';
  return `<dialog class="chat-pause-dialog" id="chat-pause-dialog" aria-labelledby="chat-pause-dialog-title">
    <form method="dialog" id="chat-pause-form">
      <h2 id="chat-pause-dialog-title">${title}</h2><p>${description}</p>
      <label for="chat-pause-reason">Gerekçe</label>
      <textarea id="chat-pause-reason" rows="3" maxlength="280" required aria-describedby="chat-pause-hint chat-pause-error"></textarea>
      <span class="field-hint" id="chat-pause-hint">Deftere yazılır, vatandaşa gösterilmez. Kişi adı yazmayın.</span>
      <span class="field-error" id="chat-pause-error" hidden>Gerekçe yazın.</span>
      <div class="chat-pause-actions"><button type="button" class="btn" data-cancel>Vazgeç</button>
        <button type="submit" class="${actionClass}" value="save">${action}</button></div>
    </form>
  </dialog>`;
}

function badgeText(state) {
  return state?.paused ? `Sohbet durduruldu · ${clock(state.since)}` : '';
}

function stateLine(state) {
  if (!state?.since) return 'Açık. Bu sunucuda henüz durdurma kararı yok.';
  const status = state.paused ? 'Durduruldu:' : 'Açık. Son karar';
  const time = clock(state.since);
  const role = esc(state.by_role || 'Simüle operatör');
  const reason = esc(state.reason || '');
  return `${status} ${time}, ${role}. Gerekçe: ${reason}`;
}

function pauseRequest(paused, reason) {
  const cleaned = String(reason || '').trim();
  return cleaned ? { paused, reason: cleaned } : null;
}

function addStylesheet(doc) {
  if (doc.querySelector('link[data-service-status-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/service_status.css';
  link.dataset.serviceStatusStyles = 'true';
  doc.head.append(link);
}

function mountChatPause(doc) {
  const main = doc.getElementById('main');
  if (!main) return;
  addStylesheet(doc);
  let section = doc.getElementById('chat-pause');
  if (!section) {
    const anchor = main.querySelector('section[aria-labelledby="stats-title"]');
    const receipt = doc.getElementById('service-receipt');
    const template = doc.createElement('template');
    template.innerHTML = sectionMarkup();
    section = template.content.firstElementChild;
    if (receipt && main.contains(receipt)) receipt.before(section);
    else if (anchor) anchor.before(section);
    else main.prepend(section);
  }
  const actions = doc.querySelector('.topbar-actions');
  if (actions && !doc.getElementById('chat-pause-badge')) {
    const badge = doc.createElement('span');
    badge.id = 'chat-pause-badge';
    badge.className = 'tag is-bad chat-pause-badge';
    badge.hidden = true;
    const ledger = doc.getElementById('ledger-badge');
    if (ledger && actions.contains(ledger)) ledger.before(badge);
    else actions.prepend(badge);
  }
  let dialog = doc.getElementById('chat-pause-dialog');
  if (!dialog) {
    const template = doc.createElement('template');
    template.innerHTML = dialogMarkup(false);
    dialog = template.content.firstElementChild;
    doc.body.append(dialog);
  }
  const toggle = doc.getElementById('chat-pause-switch');
  const line = doc.getElementById('chat-pause-state');
  const badge = doc.getElementById('chat-pause-badge');
  const form = doc.getElementById('chat-pause-form');
  const reason = doc.getElementById('chat-pause-reason');
  const error = doc.getElementById('chat-pause-error');
  let state = null;
  let timer = null;
  let busy = false;

  function render(next) {
    state = next;
    toggle.setAttribute('aria-checked', String(!next.paused));
    toggle.querySelector('.chat-pause-label').textContent = next.paused ? 'Vatandaş sohbeti durduruldu' : 'Vatandaş sohbeti açık';
    line.className = 'status-line';
    line.innerHTML = stateLine(next);
    badge.textContent = badgeText(next);
    badge.hidden = !next.paused;
  }

  async function load() {
    if (MOCK) {
      toggle.setAttribute('aria-disabled', 'true');
      line.textContent = 'Örnek veri modunda anahtar kapalı.';
      return;
    }
    try {
      render(await get(PAUSE_PATH));
      toggle.removeAttribute('aria-disabled');
    } catch {
      toggle.setAttribute('aria-disabled', 'true');
      line.className = 'status-line is-bad';
      line.textContent = 'Sohbet durumu okunamadı.';
    }
  }

  function openDialog() {
    if (!state || toggle.getAttribute('aria-disabled') === 'true' || busy) return;
    dialog.innerHTML = dialogMarkup(state.paused).replace(/^<dialog[^>]*>|<\/dialog>$/g, '');
    const input = doc.getElementById('chat-pause-reason');
    const hint = doc.getElementById('chat-pause-hint');
    const errorNode = doc.getElementById('chat-pause-error');
    const activeForm = doc.getElementById('chat-pause-form');
    const cancel = dialog.querySelector('[data-cancel]');
    cancel.addEventListener('click', () => dialog.close());
    activeForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = pauseRequest(!state.paused, input.value);
      if (!body) {
        errorNode.hidden = false;
        input.focus();
        return;
      }
      errorNode.hidden = true;
      busy = true;
      try {
        const updated = await post(PAUSE_PATH, body);
        render(updated);
        line.textContent = `${updated.message} ${stateLine(updated)}`;
        doc.dispatchEvent(new CustomEvent('nabiz:ledger-changed'));
        dialog.close();
      } catch (err) {
        if (err.status === 409) {
          await load();
          line.textContent = `Durum başka bir oturumda değişmiş; güncel hâli gösteriliyor. ${stateLine(state)}`;
        } else {
          line.className = 'status-line is-bad';
          line.textContent = err.message || 'Karar kaydedilemedi.';
        }
      } finally {
        busy = false;
      }
    });
    dialog.addEventListener('close', () => toggle.focus(), { once: true });
    dialog.showModal();
    input.focus();
  }

  toggle.addEventListener('click', openDialog);
  if (MOCK) {
    toggle.setAttribute('aria-disabled', 'true');
    line.textContent = 'Örnek veri modunda anahtar kapalı.';
  } else {
    void load();
    timer = setInterval(load, POLL_MS);
    doc.addEventListener('visibilitychange', () => {
      if (doc.hidden) {
        clearInterval(timer);
        timer = null;
      } else {
        if (timer === null) timer = setInterval(load, POLL_MS);
        void load();
      }
    });
  }
}

if (typeof document !== 'undefined') mountChatPause(document);

export { PAUSE_PATH, POLL_MS, sectionMarkup, dialogMarkup, badgeText, stateLine, pauseRequest, mountChatPause };
