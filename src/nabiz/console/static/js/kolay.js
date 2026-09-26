import { AI_NOTICE, privacyBandMarkup } from './disclosure.js';
import { esc, trName } from './format.js';
import { arrivalDisplay } from './cards.js';
import { quoteBox } from './transcript.js';
import { readProfile, readMemory, effectiveNeeds } from './profile.js';
import { HISTORY_TURNS } from './config.js';
import { ageText, ageSentence, sourceLabel, AUTHOR_TR } from './provenance.js';

const KOLAY_KEY = 'nabiz.kolay.v1';
const GAS_LINE = 'İGDAŞ 187 Doğal Gaz Acil Hattı';

function finalText(data, unknownText) {
  const mode = data.mode || (data.refused ? 'refused' : 'answer');
  if (mode === 'redirect' && data.emergency === true) return 'Bu acil bir durum olabilir. Hemen arayın.';
  if (mode === 'unknown' || mode === 'refused') return unknownText;
  return data.answer_text ?? data.answer ?? '';
}

function call153() {
  return '<a class="kolay-call" href="tel:153">153\'ü ara</a>';
}

function answerMarkup(data) {
  const mode = data.mode || (data.refused ? 'refused' : 'answer');
  if (mode === 'redirect' && data.emergency === true) {
    return '<div class="kolay-emergency" role="alert">'
      + '<a class="kolay-call" href="tel:112">112 Acil</a>'
      + (data.hazard === 'gas' ? `<a class="kolay-call kolay-call-187" href="tel:187">${GAS_LINE}</a>` : '')
      + '<a class="kolay-call" href="tel:153">153 İBB</a></div>';
  }
  if (mode === 'unknown' || mode === 'refused') return call153();

  const citations = Array.isArray(data.citations) ? data.citations.filter((item) => item && typeof item === 'object') : [];
  if (mode === 'quote_only') {
    const quotes = citations.filter((item) => typeof item.quote === 'string' && item.quote);
    return quoteBox(quotes) + call153();
  }

  const steps = Array.isArray(data.steps) ? data.steps : [];
  const first = citations[0];
  const source = first ? `${first.institution || sourceLabel(first.source)} · ${ageText(first)}` : '';
  const author = AUTHOR_TR[data.author] || data.author || 'bilinmiyor';
  const url = citations.map((item) => item.url || item.source_url).find((value) => /^https?:\/\//.test(value || ''));
  const stepsMarkup = steps.length
    ? `<ol class="kolay-steps">${steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol>` : '';
  const sourceMarkup = first ? `<p class="kolay-source">${esc(source)}</p>` : '';
  const linkMarkup = url
    ? '<a class="kolay-link" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Resmî kaynağı aç</a>' : '';
  return stepsMarkup + sourceMarkup + linkMarkup
    + `<p class="kolay-author">cevabı yazan: ${esc(author)}</p>` + call153();
}

function renderFinal(li, data, unknownText) {
  const text = li.querySelector('.chat-text');
  const final = li.querySelector('.chat-final');
  const progress = li.querySelector('.kolay-progress');
  const mode = data.mode || (data.refused ? 'refused' : 'answer');
  text.textContent = finalText(data, unknownText);
  final.innerHTML = answerMarkup(data);
  if (progress) progress.hidden = true;
  if (li.dataset) li.dataset.ruleId = data.rule_id || '';
  if (mode === 'redirect' && data.emergency === true) li.classList.add('is-emergency');
  if (mode === 'refused' || mode === 'unknown') li.classList.add('is-refused');
  li.setAttribute('aria-busy', 'false');
}

function arrivalMarkup(data) {
  const display = arrivalDisplay(data);
  const numeric = /^\d+ dk$/.test(display);
  const explanation = numeric
    ? `Tahmini varış. ${ageSentence(data.provenance)}`
    : display === 'tarifeye göre'
      ? 'Canlı araç konumu yok ya da eski. Bu yüzden dakika vermiyoruz.'
      : 'Kaynağa şu an ulaşılamadı. Bu yüzden dakika vermiyoruz.';
  return '<li class="kolay-arrival" aria-labelledby="kolay-arrival-t">'
    + `<p id="kolay-arrival-t">${esc(data.line)} · ${esc(trName(data.stop))}</p>`
    + `<p class="kolay-minute">${esc(display)}</p><p class="kolay-arrival-note">${explanation}</p></li>`;
}

function readSavedStop(storage) {
  try {
    const raw = storage.getItem(KOLAY_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    if (typeof value.line !== 'string' || typeof value.stop !== 'string') return null;
    const line = value.line.trim();
    const stop = value.stop.trim();
    if (!line || line.length > 12 || !stop || stop.length > 80) return null;
    return { line, stop };
  } catch (err) {
    return null;
  }
}

function saveStop(storage, stop, nowIso) {
  try {
    const line = String(stop?.line || '').trim();
    const name = String(stop?.stop || '').trim();
    if (!line || line.length > 12 || !name || name.length > 80) return false;
    storage.setItem(KOLAY_KEY, JSON.stringify({ line, stop: name, saved_at: nowIso }));
    return true;
  } catch (err) {
    return false;
  }
}

function forgetStop(storage) {
  try { storage.removeItem(KOLAY_KEY); return true; } catch (err) { return false; }
}

async function boot() {
  if (typeof document === 'undefined') return;
  const aiBand = document.getElementById('kolay-ai-band');
  const privacy = document.getElementById('kolay-privacy');
  if (aiBand) aiBand.textContent = AI_NOTICE;
  if (privacy) privacy.innerHTML = privacyBandMarkup();

  const log = document.getElementById('chat-log');
  const status = document.getElementById('kolay-status');
  const [{ MOCK, get, stream }, { UNKNOWN_TEXT }] = await Promise.all([
    import('./api.js'), import('./chat.js'),
  ]);
  if (!log) return;
  if (MOCK) {
    log.innerHTML = '<li class="kolay-mock-message">Örnek veri modu bu sayfada kapalı. Adresi ?mock=1 olmadan açın.<p>'
      + call153() + '</p></li>';
    return;
  }

    const sorButton = document.getElementById('kolay-sor');
    const stopButton = document.getElementById('kolay-durak');
    const sorPanel = document.getElementById('kolay-panel-sor');
    const stopPanel = document.getElementById('kolay-panel-durak');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatSubmit = document.getElementById('chat-submit');
    const stopForm = document.getElementById('kolay-stop-form');
    const lineInput = document.getElementById('kolay-line');
    const stopInput = document.getElementById('kolay-stop');
    const remember = document.getElementById('kolay-remember');
    const savedPanel = document.getElementById('kolay-stop-saved');
    const history = [];
    let activeController = null;

    const say = (message) => { if (status) status.textContent = message; };
    const storage = () => {
      try { return window.localStorage; } catch (err) { return null; }
    };
    const cancelActive = () => {
      const hadActiveRequest = Boolean(activeController);
      if (activeController) activeController.abort();
      activeController = null;
      if (hadActiveRequest) log.replaceChildren();
      log.setAttribute('aria-busy', 'false');
      chatSubmit.disabled = false;
    };
    const showPanel = (panelName) => {
      cancelActive();
      const asking = panelName === 'sor';
      sorPanel.hidden = !asking;
      stopPanel.hidden = asking;
      sorButton.setAttribute('aria-expanded', String(asking));
      stopButton.setAttribute('aria-expanded', String(!asking));
    };

    function showStopForm(stop) {
      savedPanel.hidden = true;
      stopForm.hidden = false;
      lineInput.value = stop?.line || '';
      stopInput.value = stop?.stop || '';
      remember.checked = Boolean(stop);
    }

    function showSavedStop(stop) {
      stopForm.hidden = true;
      savedPanel.hidden = false;
      savedPanel.innerHTML = `<p class="kolay-saved-name">${esc(stop.line)} · ${esc(trName(stop.stop))}</p>`
        + '<div class="kolay-saved-actions">'
        + '<button type="button" data-stop-action="refresh">Yenile</button>'
        + '<button type="button" data-stop-action="change">Durağı değiştir</button>'
        + '<button type="button" data-stop-action="forget">Unut</button></div>';
    }

    async function loadArrival(stop) {
      cancelActive();
      const controller = new AbortController();
      activeController = controller;
      log.innerHTML = '<li class="kolay-arrival is-loading" aria-busy="true"><p>Varış bilgisi alınıyor.</p></li>';
      log.setAttribute('aria-busy', 'true');
      say('Varış bilgisi alınıyor.');
      try {
        const data = await get('/api/arrival', { line: stop.line, stop: stop.stop }, controller.signal);
        if (controller.signal.aborted) return;
        log.innerHTML = arrivalMarkup(data);
        say(`Varış bilgisi: ${arrivalDisplay(data)}.`);
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err.status === 400) {
          showStopForm(stop);
          stopInput.focus();
        }
        log.innerHTML = `<li class="is-error" role="alert"><p>${esc(err.message || 'Varış bilgisi alınamadı.')}</p></li>`;
        say(err.message || 'Varış bilgisi alınamadı.');
      } finally {
        if (activeController === controller) {
          log.setAttribute('aria-busy', 'false');
          activeController = null;
        }
      }
    }

    async function ask(question) {
      cancelActive();
      const controller = new AbortController();
      activeController = controller;
      const userItem = document.createElement('li');
      userItem.className = 'chat-msg is-user';
      const questionText = document.createElement('p');
      questionText.className = 'chat-text kolay-q';
      questionText.textContent = `Sorunuz: ${question}`;
      userItem.append(questionText);
      const card = document.createElement('li');
      card.className = 'chat-msg is-assistant kolay-answer';
      card.setAttribute('aria-busy', 'true');
      const progress = document.createElement('p');
      progress.className = 'kolay-progress';
      progress.textContent = 'Cevap hazırlanıyor.';
      const text = document.createElement('p');
      text.className = 'chat-text';
      const final = document.createElement('div');
      final.className = 'chat-final kolay-final';
      card.append(progress, text, final);
      log.replaceChildren(userItem, card);
      log.setAttribute('aria-busy', 'true');
      chatSubmit.disabled = true;
      say('Cevap hazırlanıyor.');

      let streamed = '';
      let finalData = null;
      const onEvent = (event, data) => {
        if (event === 'token') {
          streamed += (data && data.text) || '';
          text.textContent = streamed;
        } else if (event === 'tool') {
          progress.textContent = 'İBB verisine bakılıyor.';
        } else if (event === 'final') {
          finalData = data;
        } else if (event === 'error') {
          throw new Error((data && data.message) || 'Sunucu bir hata bildirdi.');
        }
      };

      try {
        await stream('/api/chat?lang=tr', {
          message: question,
          needs: effectiveNeeds(readProfile(), readMemory()),
          history: history.slice(-HISTORY_TURNS * 2),
        }, onEvent, controller.signal);
        if (controller.signal.aborted || activeController !== controller) return;
        if (!finalData) throw new Error('Yanıt tamamlanmadı.');
        renderFinal(card, finalData, unknownText);
        log.setAttribute('aria-busy', 'false');
        const mode = finalData.mode || (finalData.refused ? 'refused' : 'answer');
        const emergency = mode === 'redirect' && finalData.emergency === true;
        if (!emergency) history.push({ role: 'user', content: question });
        if (!emergency && !finalData.refused && mode !== 'unknown') {
          history.push({ role: 'assistant', content: finalText(finalData, unknownText) || streamed });
        }
        say(emergency ? 'Acil iletişim bilgileri gösterildi.' : 'Yanıt hazır.');
      } catch (err) {
        if (controller.signal.aborted || activeController !== controller) return;
        card.classList.add('is-error');
        text.textContent = err.message || 'Yanıt alınamadı.';
        progress.hidden = true;
        final.innerHTML = call153();
        card.setAttribute('aria-busy', 'false');
        log.setAttribute('aria-busy', 'false');
        say(err.message || 'Yanıt alınamadı.');
      } finally {
        if (activeController === controller) {
          chatSubmit.disabled = false;
          activeController = null;
        }
      }
    }

    sorButton.addEventListener('click', () => {
      showPanel('sor');
      chatInput.focus();
    });
    stopButton.addEventListener('click', () => {
      showPanel('durak');
      const saved = readSavedStop(storage());
      if (saved) {
        showSavedStop(saved);
        void loadArrival(saved);
      } else {
        showStopForm(null);
        lineInput.focus();
      }
    });
    chatForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const question = chatInput.value.trim();
      const error = chatForm.querySelector('.field-error');
      if (!question) {
        if (error) error.hidden = false;
        chatInput.focus();
        return;
      }
      if (error) error.hidden = true;
      chatInput.value = '';
      void ask(question);
      chatInput.focus();
    });
    stopForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const line = lineInput.value.trim();
      const stop = stopInput.value.trim();
      const lineError = document.getElementById('kolay-line-error');
      const stopError = document.getElementById('kolay-stop-error');
      if (lineError) lineError.hidden = Boolean(line);
      if (stopError) stopError.hidden = Boolean(stop);
      if (!line || !stop) {
        (!line ? lineInput : stopInput).focus();
        return;
      }
      const saved = { line, stop };
      if (remember.checked) {
        if (saveStop(storage(), saved, new Date().toISOString())) showSavedStop(saved);
        else say('Bu cihazda durak hatırlanamadı.');
      } else {
        forgetStop(storage());
      }
      void loadArrival(saved);
    });
    savedPanel.addEventListener('click', (event) => {
      const action = event.target.closest('[data-stop-action]')?.getAttribute('data-stop-action');
      if (!action) return;
      const saved = readSavedStop(storage());
      if (!saved) return;
      if (action === 'refresh') void loadArrival(saved);
      if (action === 'change') {
        cancelActive();
        showStopForm(saved);
        lineInput.focus();
      }
      if (action === 'forget') {
        forgetStop(storage());
        showStopForm(null);
        lineInput.focus();
        say('Kayıtlı durak silindi.');
      }
    });

    if (window.location.hash === '#sor') {
      showPanel('sor');
      chatInput.focus();
    } else if (window.location.hash === '#durak') {
      showPanel('durak');
      const saved = readSavedStop(storage());
      if (saved) {
        showSavedStop(saved);
        void loadArrival(saved);
      } else {
        showStopForm(null);
        lineInput.focus();
      }
  }
}

export {
  answerMarkup, finalText, renderFinal, arrivalMarkup, KOLAY_KEY, GAS_LINE, readSavedStop, saveStop, forgetStop, boot,
};

if (typeof document !== 'undefined') boot();
