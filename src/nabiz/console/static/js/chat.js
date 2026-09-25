/* The assistant panel: a question goes to POST /api/chat, the answer streams back as events (token,
 * tool, final). Tokens are written as they arrive; the final event is authoritative and carries the
 * citations, the author and, sometimes, a memory suggestion the visitor confirms or declines.
 *
 * Screen readers: the log is aria-live and aria-busy while a reply streams, so it is read once when
 * the reply is complete rather than word by word; #chat-status says the state in one sentence. */

import { stream } from './api.js';
import { HISTORY_TURNS } from './config.js';
import { esc } from './format.js';
import { icon } from './icons.js';
import { citations } from './provenance.js';

const AUTHOR_TR = { model: 'model', 'yerel model': 'yerel model', kural: 'kural' };

function refusalNote() {
  return `<div class="callout callout-warn">${icon('info-circle')}<div>`
    + '<p class="callout-title">Bu soruda asistan cevap üretmez.</p>'
    + '<p>Hak, ücret, ceza ve sağlık sorularının doğru adresi 153 Çözüm Merkezi ve resmî sayfalardır. '
    + '<a href="tel:153">153\'ü arayın</a> ya da '
    + '<a href="https://www.ibb.istanbul/" target="_blank" rel="noopener noreferrer">ibb.istanbul</a> sayfasına bakın. '
    + 'Acil durumda 112.</p></div></div>';
}

function suggestionBox(suggestion) {
  const box = document.createElement('div');
  box.className = 'chat-suggest';
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Hafıza önerisi');
  box.innerHTML = `<p>Profiline ekleyeyim mi? <b>${esc(suggestion.label || suggestion.key)}</b></p>`
    + '<div class="btn-row"><button type="button" class="btn btn-primary" data-act="add">Ekle</button>'
    + '<button type="button" class="btn" data-act="skip">Hayır</button></div>'
    + '<p class="field-hint">Onaylamazsan hiçbir şey kaydedilmez. Kayıt yalnız bu tarayıcıda durur.</p>';
  return box;
}

function message(cls, inner) {
  const li = document.createElement('li');
  li.className = `chat-msg ${cls}`;
  li.innerHTML = inner;
  return li;
}

/**
 * Wire the panel. `getNeeds` returns the functional constraints allowed to leave the device;
 * `onMemorySuggestion(suggestion)` stores a confirmed suggestion and returns true when it did.
 */
function mountChat({ log, form, input, submit, status, getNeeds, onMemorySuggestion }) {
  const history = [];
  let controller = null;

  const say = (text) => { status.textContent = text; };
  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  function renderFinal(shell, data, question, streamed) {
    const textEl = shell.querySelector('.chat-text');
    const finalEl = shell.querySelector('.chat-final');
    const answer = data.answer || streamed;
    textEl.textContent = answer;
    let html = '';
    if (data.refused) { shell.classList.add('is-refused'); html += refusalNote(); }
    html += citations(data.citations);
    html += `<p class="chat-foot"><span>cevabı yazan: <b>${esc(AUTHOR_TR[data.author] || data.author || 'bilinmiyor')}</b></span></p>`;
    finalEl.innerHTML = html;
    history.push({ role: 'user', content: question }, { role: 'assistant', content: answer });
    if (data.memory_suggestion && onMemorySuggestion) {
      const box = suggestionBox(data.memory_suggestion);
      box.addEventListener('click', (evt) => {
        const btn = evt.target.closest('button[data-act]');
        if (!btn) return;
        const added = btn.dataset.act === 'add' && onMemorySuggestion(data.memory_suggestion);
        box.innerHTML = added
          ? '<p>Eklendi. Hafızam bölümünde görünür; istediğin an silebilirsin.</p>'
          : '<p>Eklenmedi.</p>';
      });
      finalEl.appendChild(box);
    }
    shell.setAttribute('aria-busy', 'false');
    say(data.refused ? 'Asistan bu soruda cevap üretmedi; 153 ve resmî sayfaya yönlendirdi.' : 'Yanıt hazır.');
    scrollDown();
  }

  async function ask(question) {
    if (controller) controller.abort();
    controller = new AbortController();
    log.appendChild(message('is-user', `<p class="chat-who">Siz</p><p class="chat-text">${esc(question)}</p>`));
    const shell = message('is-assistant', '<p class="chat-who">Asistan</p><p class="chat-tool" hidden></p>'
      + '<p class="chat-text"></p><div class="chat-final"></div>');
    shell.setAttribute('aria-busy', 'true');
    log.appendChild(shell);
    log.setAttribute('aria-busy', 'true');
    submit.setAttribute('aria-disabled', 'true');
    say('Asistan yanıt yazıyor.');
    scrollDown();
    const textEl = shell.querySelector('.chat-text');
    const toolEl = shell.querySelector('.chat-tool');
    let streamed = '';
    let finalData = null;
    const onEvent = (event, data) => {
      if (event === 'token') {
        streamed += (data && data.text) || '';
        textEl.textContent = streamed;
        scrollDown();
      } else if (event === 'tool') {
        const running = data && data.status === 'start';
        toolEl.hidden = false;
        toolEl.className = `chat-tool ${running ? 'is-running' : 'is-done'}`;
        toolEl.innerHTML = `${icon(running ? 'refresh' : 'circle-check')}<span>${running ? 'Araç çalışıyor' : 'Araç tamamlandı'}: `
          + `${esc((data && data.name) || 'araç')}</span>`;
      } else if (event === 'final') {
        finalData = data;
      } else if (event === 'error') {
        throw new Error((data && data.message) || 'Sunucu bir hata bildirdi.');
      }
    };
    try {
      await stream('/api/chat', { message: question, needs: getNeeds(), history: history.slice(-HISTORY_TURNS * 2) },
        onEvent, controller.signal);
      if (finalData) renderFinal(shell, finalData, question, streamed);
      else { shell.setAttribute('aria-busy', 'false'); say('Yanıt tamamlanmadı.'); }
    } catch (err) {
      if (controller.signal.aborted) return;
      shell.classList.add('is-error');
      textEl.textContent = err.message || 'Yanıt alınamadı.';
      shell.setAttribute('aria-busy', 'false');
      say('Yanıt alınamadı.');
    } finally {
      log.setAttribute('aria-busy', 'false');
      submit.removeAttribute('aria-disabled');
    }
  }

  form.addEventListener('submit', (evt) => {
    evt.preventDefault();
    if (submit.getAttribute('aria-disabled') === 'true') return;
    const question = input.value.trim();
    const error = form.querySelector('.field-error');
    if (!question) {
      if (error) error.hidden = false;
      input.focus();
      return;
    }
    if (error) error.hidden = true;
    input.value = '';
    ask(question);
    input.focus();
  });

  return { ask };
}

export { mountChat, refusalNote };
