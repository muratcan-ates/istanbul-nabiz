/* The assistant panel: a question goes to POST /api/chat, the answer streams back as events (token,
 * tool, final). Tokens are written as they arrive; the final event is authoritative and carries the
 * citations, the author and, sometimes, a memory suggestion the visitor confirms or declines.
 *
 * Screen readers: the log is aria-live and aria-busy while a reply streams, so it is read once when
 * the reply is complete rather than word by word; #chat-status says the state in one sentence. */

import { stream } from './api.js';
import { HISTORY_TURNS } from './config.js';
import { dateTime, esc, has, int, num } from './format.js';
import { icon } from './icons.js';
import { AUTHOR_TR, TOOL_TR, ageText, howPanel, sourceLabel, sourceLink } from './provenance.js';

const UNKNOWN_TEXT = "Bu konuda doğrulayabildiğim güncel bir İBB kaynağı bulamadım. Tahmin yürütmek istemiyorum. 153'e bağlanabilir veya ilgili resmî sayfaya gidebilirsin.";
const AI_NOTICE = 'Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim.';
const EMERGENCY_TEXT = 'Bu acil bir durum olabilir. Lütfen doğrudan ara: 112 (Acil) veya 153 (İBB).';

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

function sourceItem(item) {
  const place = item.institution || sourceLabel(item.source) || 'Kurum bilinmiyor';
  const title = item.title || item.source || 'Başlık bilinmiyor';
  const updated = item.source_updated_at
    ? `güncelleme ${dateTime(item.source_updated_at)}` : 'güncelleme tarihi kaynakta yok';
  const fetchedAt = item.fetched_at || item.observed_at;
  const fetched = fetchedAt ? `alınma ${dateTime(fetchedAt)}` : 'alınma tarihi bilinmiyor';
  const link = sourceLink({ source: item.source || place, url: item.url || item.source_url });
  return `<li class="cite">${esc(place)} · ${esc(title)} · ${esc(updated)} · ${esc(fetched)} ${link}</li>`;
}

function answerCard(data, turnId) {
  const mode = data.mode || (data.refused ? 'refused' : 'answer');
  const how = data.how;
  if (mode === 'redirect' && data.emergency === true) {
    return `<div class="callout callout-warn" role="alert"><div><p>${EMERGENCY_TEXT}</p>`
      + '<div class="btn-row"><a class="btn btn-danger" href="tel:112">112 (Acil)</a>'
      + '<a class="btn btn-primary" href="tel:153">153 (İBB)</a></div></div></div>';
  }

  const unknown = mode === 'unknown' || mode === 'refused';
  const answer = unknown ? UNKNOWN_TEXT : (data.answer_text ?? data.answer ?? '');
  const cited = Array.isArray(data.citations) ? data.citations.filter(Boolean) : [];
  const steps = Array.isArray(data.steps) ? data.steps : [];
  const first = cited[0];
  const author = AUTHOR_TR[data.author] || data.author || 'bilinmiyor';
  const source = first ? sourceLabel(first.institution || first.source) : 'kaynak yok';
  const age = first ? ageText(first) : 'veri yaşı bilinmiyor';
  const calls = how && Number.isFinite(Number(how.tool_calls)) ? int(how.tool_calls) : '0';
  const elapsed = how && has(how.elapsed_s) ? num(how.elapsed_s, 1) : 'bilinmiyor';
  let html = '<section class="answer-short"><h3>KISA CEVAP</h3>'
    + `<p>${esc(answer)}</p></section>`;
  if (!unknown && mode === 'quote_only' && first && typeof first.quote === 'string') {
    html += `<blockquote class="quote-exact">${esc(first.quote)}</blockquote>`;
  }
  if (!unknown && steps.length) {
    html += `<section><h3>NASIL YAPILIR</h3><ol>${steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol></section>`;
  }
  if (!unknown) {
    html += `<section><h3>KAYNAK</h3>${cited.length
      ? `<ul class="cites">${cited.map(sourceItem).join('')}</ul>` : '<p>Kaynak yok.</p>'}</section>`;
  }
  const officialLinks = !unknown ? cited.map((item) => item.url || item.source_url).filter((url) => /^https?:\/\//.test(url || '')) : [];
  html += '<div class="btn-row">';
  officialLinks.forEach((url) => {
    html += `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">Resmî kaynağı aç</a>`;
  });
  html += '<a class="btn btn-primary" href="tel:153">153\'e sor</a></div>';
  if (!unknown) {
    html += `<p class="chat-foot"><span>${esc(source)} · ${esc(age)} · cevabı yazan: <b>${esc(AUTHOR_TR[data.author] || author)}</b>`
      + ` · ${esc(calls)} araç çağrısı · ${esc(elapsed)} sn</span></p>`;
    html += howPanel(how, turnId);
    html += `<div class="feedback-slot" data-turn-id="${esc(turnId)}"></div>`;
  }
  return html;
}

/**
 * Wire the panel. `getNeeds` returns the functional constraints allowed to leave the device;
 * `onMemorySuggestion(suggestion)` stores a confirmed suggestion and returns true when it did.
 */
function mountChat({ log, form, input, submit, status, getNeeds, onMemorySuggestion }) {
  const history = [];
  let controller = null;
  let sessionStarted = false;
  let turnCount = 0;

  const say = (text) => { status.textContent = text; };
  const scrollDown = () => { log.scrollTop = log.scrollHeight; };

  function renderFinal(shell, data, question, streamed, turnId) {
    const textEl = shell.querySelector('.chat-text');
    const finalEl = shell.querySelector('.chat-final');
    const answer = data.answer_text ?? data.answer ?? streamed;
    const mode = data.mode || (data.refused ? 'refused' : 'answer');
    textEl.hidden = true;
    textEl.textContent = '';
    if (data.refused || mode === 'unknown') shell.classList.add('is-refused');
    if (mode === 'redirect' && data.emergency === true) shell.classList.add('is-emergency');
    finalEl.innerHTML = answerCard({ ...data, answer_text: answer }, turnId);
    // The refusal text is not context. The refused question stays so the server can refuse a
    // follow-up to it ("peki öğrenciler için?"); the server never hands it to the model.
    if (!data.emergency) history.push({ role: 'user', content: question });
    if (!data.refused && !data.emergency && mode !== 'unknown') history.push({ role: 'assistant', content: answer });
    if (data.memory_suggestion && onMemorySuggestion) {
      const box = suggestionBox(data.memory_suggestion);
      box.addEventListener('click', (evt) => {
        const btn = evt.target.closest('button[data-act]');
        if (!btn) return;
        const added = btn.dataset.act === 'add' && onMemorySuggestion(data.memory_suggestion);
        const said = typeof added === 'string' ? added : 'Eklendi. Hafızam bölümünde görünür; istediğin an silebilirsin.';
        box.innerHTML = added ? `<p>${esc(said)}</p>` : '<p>Eklenmedi.</p>';
      });
      finalEl.appendChild(box);
    }
    shell.setAttribute('aria-busy', 'false');
    say(data.emergency ? 'Acil iletişim bilgileri gösterildi.'
      : data.refused || mode === 'unknown' ? 'Asistan doğrulanmış kaynak bulamadı; 153 ve resmî sayfaya yönlendirdi.' : 'Yanıt hazır.');
    scrollDown();
  }

  async function ask(question) {
    if (controller) controller.abort();
    controller = new AbortController();
    log.appendChild(message('is-user', `<p class="chat-who">Siz</p><p class="chat-text">${esc(question)}</p>`));
    const shell = message('is-assistant', '<p class="chat-who">Asistan</p><p class="chat-tool" hidden></p>'
      + '<p class="chat-text"></p><div class="chat-final"></div>');
    const turnId = `turn-${++turnCount}`;
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
      if (event === 'session_started') {
        if (!sessionStarted) {
          sessionStarted = true;
          log.prepend(message('is-notice', `<div class="chat-band" role="note"><p>${esc(AI_NOTICE)}</p></div>`));
        }
      } else if (event === 'token') {
        streamed += (data && data.text) || '';
        textEl.textContent = streamed;
        scrollDown();
      } else if (event === 'tool') {
        const running = data && data.status === 'start';
        toolEl.hidden = false;
        toolEl.className = `chat-tool ${running ? 'is-running' : 'is-done'}`;
        toolEl.innerHTML = `${icon(running ? 'refresh' : 'circle-check')}<span>${running ? 'Araç çalışıyor' : 'Araç tamamlandı'}: `
          + `${esc(TOOL_TR[data && data.name] || 'İBB aracı')}</span>`;
      } else if (event === 'final') {
        finalData = data;
      } else if (event === 'error') {
        throw new Error((data && data.message) || 'Sunucu bir hata bildirdi.');
      }
    };
    try {
      const lang = new URLSearchParams(window.location.search).get('lang') || 'tr';
      await stream(`/api/chat?lang=${encodeURIComponent(lang)}`, { message: question, needs: getNeeds(), history: history.slice(-HISTORY_TURNS * 2) },
        onEvent, controller.signal);
      if (finalData) renderFinal(shell, finalData, question, streamed, turnId);
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

export { mountChat, refusalNote, answerCard, UNKNOWN_TEXT };
