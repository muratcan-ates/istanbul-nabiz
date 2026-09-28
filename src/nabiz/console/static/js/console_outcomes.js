/* E75's aggregate outcome board. The exported render helpers stay safe to import without a DOM. */

const STORAGE_KEY = 'nabiz.outcome-board.v1';
const WINDOWS = [7, 30];
const TEXT = {
  title: 'Sonuç panosu', lede: (days) => `Son ${days} günün kayıtlı verisinden; kişi bazında metrik yok.`,
  noSnapshot: 'Henüz kayıt yok.', lastSnapshot: (date, days) => `Son kayıt: ${date} · ${days} gün`,
  save: 'Ölçümü kaydet', nextSave: (time) => `Sonraki kayıt saati: ${time}.`,
  loading: 'Yükleniyor', error: 'Pano okunamadı. Yeniden deneyin.',
  saved: (time) => `Ölçüm kaydedildi: ${time}.`, tooSoon: 'Kaydedilemedi: son kayıttan bu yana 5 dakika geçmedi.',
  saveError: 'Ölçüm kaydedilemedi. Yeniden deneyin.', how: 'Nasıl hesaplanır',
  minRule: (min) => `Payda ${min} örneğin altındaysa yüzde ya da ortanca hesaplanmaz; ham sayı görünür.`,
  noDate: 'Ölçüm tarihi dosyada yok.',
};

const GROUP_METHODS = [
  'Talep yanıtı, penceredeki taleplerle; insan kararı, insan kararına giden kartlarla karşılaştırılır. Erteleme ve süre aşımı tamamlanma sayılmaz.',
  'Yanıt süresi talep kaydı ile ilk operatör yanıtı arasındadır; kart süresi taslak ile ilk insan kararı arasındadır.',
  'Teyit yalnız vatandaşın “Düzeldi” adımıdır; yedi gündür teyit gelmemesi teyit sayılmaz.',
  'Yeniden açılma, çözüm bildirilen kayıtların en az bir “Devam ediyor” adımı içermesidir.',
  'Bilgi dizini değerlendirme dosyasındaki “Sonra” değerleri kullanılır; bu ölçü ürün başarısını göstermez.',
];

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function int(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString('tr-TR') : '';
}

function percent(value) {
  return Number.isFinite(Number(value))
    ? new Intl.NumberFormat('tr-TR', { style: 'percent', maximumFractionDigits: 0 }).format(Number(value) / 100)
    : '';
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${int(total)} sn`;
  if (total < 3600) return `${int(Math.floor(total / 60))} dk`;
  if (total < 86400) {
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    return minutes ? `${int(hours)} sa ${int(minutes)} dk` : `${int(hours)} sa`;
  }
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  return hours ? `${int(days)} gün ${int(hours)} sa` : `${int(days)} gün`;
}

function denominatorText(item) {
  const numerator = int(item?.numerator);
  const denominator = int(item?.denominator);
  const templates = {
    o1_requests: `Yanıtlanan talep: ${numerator} · Penceredeki talep: ${denominator}`,
    o1_cards: `İnsan kararı verilen kart: ${numerator} · İnsan kararına giden kart: ${denominator}`,
    o2_reply_median: `Yanıtlı talep sayısı: ${denominator}`,
    o2_reply_p90: `Yanıtlı talep sayısı: ${denominator}`,
    o2_decision_median: `İlk insan kararı verilen kart sayısı: ${denominator}`,
    o3_confirmed: `“Düzeldi” diyen bildirim: ${numerator} · Çözüm bildirilen: ${denominator}`,
    o4_reopened: `Yeniden açılan bildirim: ${numerator} · Çözüm bildirilen: ${denominator}`,
    o5_first_source: `İlk kaynağı altın sayfa olan: ${numerator} · Altını olan yanıt: ${denominator}`,
    o5_negative_answers: `Cevap verilen: ${numerator} · Negatif küme sorusu: ${denominator}`,
  };
  return templates[item?.key] || `Örnek sayısı: ${denominator}`;
}

function readWindow(storage) {
  try {
    const target = storage ?? globalThis.localStorage;
    const parsed = JSON.parse(target.getItem(STORAGE_KEY) || 'null');
    return parsed?.version === 1 && WINDOWS.includes(parsed.days) ? parsed.days : 30;
  } catch {
    return 30;
  }
}

function savedValue(item) {
  const kind = item.kind || (String(item.key).startsWith('o2_') ? 'duration' : 'ratio');
  if (item.status === 'measured') return kind === 'ratio' ? percent(item.value) : formatDuration(item.value);
  return 'henüz ölçülmedi';
}

function metricMarkup(item, previous, minN = 10) {
  const measured = item.status === 'measured';
  const value = measured ? savedValue(item) : 'Henüz ölçülmedi';
  const denominator = item.status === 'unmeasured' ? '' : `<p class="ob-denominator">${esc(denominatorText(item))}</p>`;
  const raw = item.status === 'insufficient'
    ? `<p class="ob-reason">Ham ${item.kind === 'ratio' ? 'sayı' : 'örnek sayısı'}: ${item.kind === 'ratio' ? `${int(item.numerator)} / ${int(item.denominator)}` : int(item.denominator)}. ${esc(item.reason || TEXT.minRule(minN))}</p>`
    : item.status === 'unmeasured' ? `<p class="ob-reason">${esc(item.reason || '')}</p>` : '';
  const old = previous ? `<p class="ob-previous">Önceki kayıt: ${esc(savedValue(previous))}`
    + `${previous.status === 'unmeasured' ? '' : ` · ${esc(denominatorText(previous))}`}</p>` : '';
  const note = item.note ? `<p class="ob-note">${esc(item.note)}</p>` : '';
  return `<div class="ob-metric" data-status="${esc(item.status)}"><h4>${esc(item.label)}</h4>`
    + `<p class="ob-value">${esc(value)}</p>${denominator}${raw}`
    + `<p class="ob-source">Kaynak: ${esc(item.source)}</p>${note}${old}</div>`;
}

function formatDate(value) {
  const date = new Date(value || '');
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function formatClock(value) {
  const date = new Date(value || '');
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('tr-TR', {
    timeZone: 'Europe/Istanbul', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function countMarkup(counts) {
  const rows = [
    ['waiting_count', (n) => `Bekleyen talep: ${int(n)}`],
    ['oldest_waiting_s', (n) => `En eski bekleyen talep yaşı: ${formatDuration(n)}`],
    ['expired', (n) => `Süresi dolan kart: ${int(n)}`],
    ['deferred_or_waiting', (n) => `Ertelenen ya da bekleyen kart: ${int(n)}`],
    ['closed_by_reflex', (n) => `Kural ile kapanan: ${int(n)}`],
    ['no_reply_7_days', (n) => `7 gündür teyit gelmedi: ${int(n)}`],
    ['timeline_skipped', (n) => `Bozuk zaman çizgisi satırı atlandı: ${int(n)}`],
  ].filter(([key]) => counts?.[key] !== null && counts?.[key] !== undefined && Number.isFinite(Number(counts[key])));
  return rows.length ? `<p class="ob-counts">${rows.map(([key, label]) => `<span>${esc(label(counts[key]))}</span>`).join('')}</p>` : '';
}

function boardMarkup(data, previous = null, canSave = true, nextSaveAt = null, lastSnapshot = previous) {
  const days = WINDOWS.includes(data?.window_days) ? data.window_days : 30;
  const oldByKey = new Map((previous?.metrics || []).map((item) => [item.key, item]));
  const groups = (data?.groups || []).map((group, index) => `<section class="ob-group" aria-labelledby="ob-${esc(group.key)}-title">`
    + `<h3 id="ob-${esc(group.key)}-title">${esc(group.title)}</h3>`
    + `${(group.metrics || []).map((item) => metricMarkup(item, oldByKey.get(item.key), data.min_n)).join('')}`
    + `${countMarkup(group.counts)}`
    + `${group.key === 'O5' ? `<p class="ob-source">${TEXT.noDate}</p>` : ''}</section>`).join('');
  const last = lastSnapshot ? TEXT.lastSnapshot(formatDate(lastSnapshot.taken_at), lastSnapshot.window_days) : TEXT.noSnapshot;
  const disabled = canSave ? '' : ' aria-disabled="true"';
  const cooldown = canSave ? '' : `<p class="ob-save-note">${esc(TEXT.nextSave(formatClock(nextSaveAt)))}</p>`;
  return `<section class="outcome-board" id="outcome-board" aria-labelledby="outcome-board-title">`
    + `<h2 id="outcome-board-title">${TEXT.title}</h2><p class="ob-lede">${esc(TEXT.lede(days))}</p>`
    + `<p class="ob-last-record" data-ob-last>${esc(last)}</p>`
    + `<fieldset class="ob-window"><legend class="ob-visually-hidden">Pencere</legend>`
    + WINDOWS.map((day) => `<label><input type="radio" name="ob-window" value="${day}"${day === days ? ' checked' : ''}>`
      + `<span>${day} gün</span></label>`).join('') + `</fieldset>`
    + `<div class="ob-groups">${groups}</div>`
    + `<details class="ob-how"><summary>${TEXT.how}</summary><ul>${GROUP_METHODS.map((line) => `<li>${esc(line)}</li>`).join('')}`
    + `<li>${esc(TEXT.minRule(data?.min_n || 10))}</li></ul></details>`
    + `<button type="button" class="btn btn-primary" data-ob-save${disabled}>${TEXT.save}</button>${cooldown}`
    + `<p class="ob-status" role="status" aria-live="polite"></p></section>`;
}

function addStylesheet() {
  if (document.querySelector('link[href="/css/console_outcomes.css"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/console_outcomes.css';
  document.head.append(link);
}

function placeBoard() {
  const existing = document.getElementById('outcome-board');
  if (existing) return existing;
  const board = document.createElement('section');
  const anchor = document.getElementById('outcomes-mount') || document.getElementById('approval-health') || document.getElementById('day');
  if (anchor) anchor.after(board);
  else document.querySelector('main#main')?.append(board);
  return board.isConnected ? board : null;
}

async function mount() {
  const api = await import('./api.js');
  if (api.MOCK) return;
  const host = placeBoard();
  if (!host) return;
  addStylesheet();
  let currentHost = host;
  let days = readWindow();
  let data = null;
  let previous = null;
  let canSave = true;
  let nextSaveAt = null;
  let pendingRefresh = null;
  const status = (message) => {
    const node = document.getElementById('outcome-board')?.querySelector('.ob-status');
    if (node) node.textContent = message;
  };
  const render = () => {
    const template = document.createElement('template');
    template.innerHTML = data ? boardMarkup(data, previous, canSave, nextSaveAt)
      : `<section class="outcome-board" id="outcome-board" aria-labelledby="outcome-board-title" aria-busy="true">`
        + `<h2 id="outcome-board-title">${TEXT.title}</h2><p class="ob-status" role="status">${TEXT.loading}</p></section>`;
    currentHost.replaceWith(template.content.firstElementChild);
    currentHost = document.getElementById('outcome-board');
  };
  const refresh = async () => {
    try {
      currentHost?.setAttribute('aria-busy', 'true');
      status(TEXT.loading);
      const result = await api.get('/api/console/outcomes', { days });
      data = result.board;
      previous = result.previous;
      canSave = result.can_save;
      nextSaveAt = result.next_save_at;
      const activeSave = document.activeElement?.matches?.('[data-ob-save]');
      const activeWindow = document.activeElement?.matches?.('input[name="ob-window"]');
      currentHost = document.getElementById('outcome-board');
      const template = document.createElement('template');
      template.innerHTML = boardMarkup(data, previous, canSave, nextSaveAt);
      currentHost.replaceWith(template.content.firstElementChild);
      currentHost = document.getElementById('outcome-board');
      currentHost?.removeAttribute('aria-busy');
      if (activeSave) document.querySelector('[data-ob-save]')?.focus();
      if (activeWindow) document.querySelector(`input[name="ob-window"][value="${days}"]`)?.focus();
    } catch {
      const current = document.getElementById('outcome-board');
      if (!current) return;
      current.removeAttribute('aria-busy');
      if (!data) current.innerHTML = `<h2 id="outcome-board-title">${TEXT.title}</h2>`
        + `<p class="ob-status" role="status">${TEXT.error}</p>`;
      else status(TEXT.error);
    }
  };
  render();
  refresh();
  document.addEventListener('change', (event) => {
    if (!(event.target instanceof Element) || !event.target.matches('input[name="ob-window"]')) return;
    days = WINDOWS.includes(Number(event.target.value)) ? Number(event.target.value) : 30;
    try { globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, days })); } catch { /* Device preference only. */ }
    refresh();
  });
  document.addEventListener('click', async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest('[data-ob-save]');
    if (!button || button.getAttribute('aria-disabled') === 'true' || button.getAttribute('aria-busy') === 'true') return;
    button.setAttribute('aria-busy', 'true');
    status('Ölçüm kaydediliyor.');
    try {
      const result = await api.post('/api/console/outcomes/snapshot', { days });
      data = result.board;
      previous = result.previous;
      canSave = false;
      nextSaveAt = new Date(Date.parse(result.saved.taken_at) + 5 * 60 * 1000).toISOString();
      const template = document.createElement('template');
      template.innerHTML = boardMarkup(data, previous, canSave, nextSaveAt, result.saved);
      document.getElementById('outcome-board').replaceWith(template.content.firstElementChild);
      currentHost = document.getElementById('outcome-board');
      const saveButton = document.querySelector('[data-ob-save]');
      saveButton?.focus();
      status(TEXT.saved(formatClock(result.saved.taken_at)));
    } catch (error) {
      if (error.status === 429) {
        await refresh();
        status(TEXT.tooSoon);
      } else status(TEXT.saveError);
      document.querySelector('[data-ob-save]')?.removeAttribute('aria-busy');
    }
  });
  for (const eventName of ['nabiz:decided', 'nabiz:ledger-changed']) {
    document.addEventListener(eventName, () => {
      if (pendingRefresh !== null) return;
      pendingRefresh = setTimeout(() => { pendingRefresh = null; refresh(); }, 1000);
    });
  }
}

if (typeof document !== 'undefined') mount();

export { TEXT, metricMarkup, boardMarkup, readWindow, formatDuration, denominatorText };
