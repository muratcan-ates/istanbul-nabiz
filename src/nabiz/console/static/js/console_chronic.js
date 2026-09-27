/* Recurring Metro observations, mounted only on the operator console. */

import { MOCK, get } from './api.js';
import { dateTime, esc, int } from './format.js';
import { loadCatalogs, t } from './i18n_text.js';

const PATH = '/api/console/chronic';
const STYLESHEET = '/css/console_chronic.css';
const ANCHORS = ['#chronic-mount', '#report-map', '#day'];
const MARKER = '#decision';
const VISIBLE_ROWS = 10;
const STALE_MS = 300_000;

function titleMarkup(row) {
  if (row.kind === 'line') {
    return `<span lang="tr">${esc(row.line || '')}</span> · ${esc(t('ui.chronic.type_line', 'hat duyurusu'))}`;
  }
  let type;
  if (row.equipment_type === 'escalator') type = esc(t('ui.chronic.type_escalator', 'yürüyen merdiven'));
  else if (row.equipment_type === 'moving_walkway') type = esc(t('ui.chronic.type_moving_walkway', 'yürüyen bant'));
  else type = esc(t('ui.chronic.type_elevator', 'asansör'));
  const station = `<strong lang="tr">${esc(row.station || '')}</strong>`;
  const line = row.line ? ` · <span lang="tr">${esc(row.line)}</span>` : '';
  return `${station}${line} · ${type}`;
}

function agencyMarkup(agency) {
  if (!agency || !agency.name) return `<p>${esc(t('ui.chronic.agency_none', 'Kurum çıkarılamadı; 153 doğru kuruma yönlendirir.'))}</p>`;
  const label = t('ui.chronic.agency', 'Önerilen kurum: {name}').replace('{name}', '').trim();
  const link = agency.url
    ? ` · <a href="${esc(agency.url)}" target="_blank" rel="noopener">${esc(t('ui.chronic.agency_link', 'resmî sayfa'))}</a>`
    : '';
  return `<p>${esc(label)} <span lang="tr">${esc(agency.name)}</span>${link}</p>`;
}

export function rowMarkup(row) {
  const chronic = row.chronic ? ` <span class="tag is-warn">${esc(t('ui.chronic.tag', 'kronik'))}</span>` : '';
  const seen = esc(t('ui.chronic.seen_days', '{read} okunan günün {seen} gününde görüldü', {
    read: int(row.read_days), seen: int(row.days_seen),
  }));
  const reads = esc(t('ui.chronic.seen_reads', '{total} okumadan {seen} tanesinde', {
    total: int(row.reads_total), seen: int(row.reads_seen),
  }));
  const dates = esc(t('ui.chronic.first_last', 'ilk {first} · son {last}', {
    first: dateTime(row.first_seen), last: dateTime(row.last_seen),
  }));
  const latest = row.in_latest_read
    ? esc(t('ui.chronic.in_latest', 'son okumada görüldü'))
    : esc(t('ui.chronic.not_in_latest', 'son okumada görülmedi'));
  const count = row.max_at_once > 1
    ? `<p>${esc(t('ui.chronic.at_once', 'aynı anda en çok {count} adet', { count: int(row.max_at_once) }))}</p>` : '';
  const statuses = (row.statuses || []).map((status) => {
    if (status === 'fault') return esc(t('ui.chronic.status_fault', 'arıza'));
    if (status === 'revision') return esc(t('ui.chronic.status_revision', 'revizyon'));
    if (status === 'not_operated') return esc(t('ui.chronic.status_not_operated', 'çalıştırılmıyor'));
    return '';
  }).filter(Boolean).join(' · ');
  const statusMarkup = statuses ? `<p>${statuses}</p>` : '';
  const notice = row.kind === 'line' && row.notice
    ? `<p class="chronic-notice" lang="tr">${esc(row.notice)}</p>` : '';
  const reports = row.reports > 0
    ? `<p>${esc(t('ui.chronic.reports', 'Vatandaş bildirimi: {count}', { count: int(row.reports) }))}</p>` : '';
  return '<li class="chronic-row">'
    + `<h3 class="chronic-row-title">${titleMarkup(row)}${chronic}</h3>`
    + `<p>${seen}</p><p>${reads}</p><p>${dates}</p><p>${latest}</p>`
    + count + statusMarkup + notice + reports + agencyMarkup(row.agency)
    + '</li>';
}

export function noteMarkup(payload) {
  const notes = [];
  for (const code of payload.note_codes || []) {
    if (code === 'equipment_thin') {
      notes.push(`<p class="chronic-note">${esc(t('ui.chronic.equipment_thin', 'Ekipman listesi bu dönemde yalnız {days} gün okundu. Kronik demek için en az {min} okunan gün gerekiyor; ekipman satırları şimdilik yalnız görülme sayısıdır.', {
        days: int(payload.coverage?.equipment?.read_days || 0), min: int(payload.chronic_min_days),
      }))}</p>`);
    } else if (code === 'lines_thin') {
      notes.push(`<p class="chronic-note">${esc(t('ui.chronic.lines_thin', 'Hat duyuruları bu dönemde yalnız {days} gün okundu. Kronik demek için en az {min} okunan gün gerekiyor.', {
        days: int(payload.coverage?.lines?.read_days || 0), min: int(payload.chronic_min_days),
      }))}</p>`);
    } else if (code === 'no_rows') {
      notes.push(`<p class="chronic-note">${esc(t('ui.chronic.no_rows', 'Bu dönemde okunan günlerde listede ekipman ya da hat duyurusu görülmedi.'))}</p>`);
    } else if (code === 'reports_unavailable') {
      notes.push(`<p class="chronic-note">${esc(t('ui.chronic.reports_unavailable', 'Karar defteri okunamadı; vatandaş bildirimi sayılmadı.'))}</p>`);
    }
  }
  return notes.join('');
}

function rowCopyText(row) {
  const days = t('ui.chronic.seen_days', '{read} okunan günün {seen} gününde görüldü', {
    read: int(row.read_days), seen: int(row.days_seen),
  });
  const agency = row.agency?.name
    ? t('ui.chronic.agency', 'Önerilen kurum: {name}', { name: row.agency.name })
    : t('ui.chronic.agency_none', 'Kurum çıkarılamadı; 153 doğru kuruma yönlendirir.');
  if (row.kind === 'line') {
    return [row.line, t('ui.chronic.type_line', 'hat duyurusu'), days, agency].filter(Boolean).join(' · ');
  }
  const type = row.equipment_type === 'escalator'
    ? t('ui.chronic.type_escalator', 'yürüyen merdiven')
    : row.equipment_type === 'moving_walkway'
      ? t('ui.chronic.type_moving_walkway', 'yürüyen bant')
      : t('ui.chronic.type_elevator', 'asansör');
  return [row.station, row.line, type, days, agency].filter(Boolean).join(' · ');
}

export function copyText(payload, includeMore = false) {
  const rows = includeMore ? payload.rows || [] : (payload.rows || []).slice(0, VISIBLE_ROWS);
  const coverage = payload.coverage || {};
  const foot = t('ui.chronic.foot', 'Arşiv süreksiz: bu dönemde ekipman listesi {equipment} gün, hat duyuruları {lines} gün okundu. Listede görülmemek, çalıştığı anlamına gelmez.', {
    equipment: int(coverage.equipment?.read_days || 0), lines: int(coverage.lines?.read_days || 0),
  });
  const triage = t('ui.chronic.triage_note', 'Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır.');
  return [...rows.map(rowCopyText), foot, triage].join('\n');
}

function reportsOnlyMarkup(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return '';
  const names = rows.slice(0, 10).map((row) =>
    `<span lang="tr">${esc(row.station)} (${int(row.reports)})</span>`).join(', ');
  const separator = '__CHRONIC_STATIONS__';
  const sentence = t('ui.chronic.reports_only',
    'Listede görülmeyen istasyonlarda vatandaş bildirimi: {stations}', { stations: separator });
  const [before, after = ''] = sentence.split(separator);
  return `<p class="chronic-reports-only">${esc(before)}${names}${esc(after)}</p>`;
}

function contentMarkup(payload) {
  const rows = payload.rows || [];
  const visible = rows.slice(0, VISIBLE_ROWS).map(rowMarkup).join('');
  const listHead = rows.length
    ? '<div class="chronic-list-head">'
      + `<h3>${esc(t('ui.chronic.list_title', 'Görülenler'))}</h3>`
      + `<button type="button" id="chronic-copy" class="btn btn-quiet">${esc(t('ui.chronic.copy', 'Listeyi kopyala'))}</button>`
      + `<span id="chronic-copy-status" class="chronic-copy-status" role="status" aria-live="polite"></span></div>` : '';
  const extra = rows.length > VISIBLE_ROWS
    ? `<details class="chronic-more"><summary>${esc(t('ui.chronic.more', 'Tümünü göster ({count})', { count: int(rows.length) }))}</summary>`
      + `<ol class="chronic-list" start="${VISIBLE_ROWS + 1}">${rows.slice(VISIBLE_ROWS).map(rowMarkup).join('')}</ol></details>` : '';
  const coverage = payload.coverage || {};
  const foot = `<p class="chronic-foot">${esc(t('ui.chronic.foot', 'Arşiv süreksiz: bu dönemde ekipman listesi {equipment} gün, hat duyuruları {lines} gün okundu. Listede görülmemek, çalıştığı anlamına gelmez.', {
    equipment: int(coverage.equipment?.read_days || 0), lines: int(coverage.lines?.read_days || 0),
  }))}</p>`;
  const triage = `<p class="chronic-triage">${esc(t('ui.chronic.triage_note', 'Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır.'))}</p>`;
  const unreadable = Number(coverage.equipment?.unreadable_reads || 0);
  const how = '<details class="chronic-how">'
    + `<summary>${esc(t('ui.chronic.how', 'Nasıl hesaplandı?'))}</summary>`
    + `<p>${esc(t('ui.chronic.how_units', 'Metro İstanbul aynı istasyondaki aynı türden ekipmanları ayıracak bir kimlik yayımlamıyor; bir satır, o istasyonda en az bir ekipmanın listede olduğunu söyler.'))}</p>`
    + `<p>${esc(t('ui.chronic.how_threshold', 'Kronik: en az {min} ayrı günde görülen satır. Bu eşik bir tasarım kararıdır, ölçülmüş bir değer değildir.', { min: int(payload.chronic_min_days) }))}</p>`
    + (unreadable > 0 ? `<p>${esc(t('ui.chronic.how_unreadable', '{count} okuma istasyon adı taşımadığı için sayılmadı.', { count: int(unreadable) }))}</p>` : '')
    + `<p>${esc(t('ui.chronic.how_reports', 'Vatandaş bildirimi doğrulanmamıştır; karar defterinden, istasyon bazında sayılır, hat ayrımı yoktur.'))}</p>`
    + '</details>';
  const reads = [coverage.equipment?.last_read, coverage.lines?.last_read].filter(Boolean).sort();
  const freshness = reads.length
    ? `<p class="chronic-freshness">${esc(t('ui.chronic.last_read', 'Son okuma: kayıtlı · {when}', { when: dateTime(reads[reads.length - 1]) }))}</p>` : '';
  return noteMarkup(payload)
    + (rows.length ? `${listHead}<ol class="chronic-list" id="chronic-list">${visible}</ol>${extra}` : '')
    + reportsOnlyMarkup(payload.reports_only)
    + foot + triage + how + freshness;
}

function titleAndDescription() {
  return `<h2 id="chronic-title">${esc(t('ui.chronic.title', 'Kronik aksaklıklar'))}</h2>`
    + `<p class="section-note">${esc(t('ui.chronic.description', "Metro İstanbul'un kullanılamayan ekipman listesi ve hat duyuruları, Nabız'ın kendi okumalarından; ayrı gün sayısına göre sıralı."))}</p>`;
}

function controlsMarkup(days = '7') {
  return '<div class="chronic-controls">'
    + `<label for="chronic-days">${esc(t('ui.chronic.period', 'Dönem'))}</label>`
    + `<select id="chronic-days"><option value="7"${days === '7' ? ' selected' : ''}>${esc(t('ui.chronic.period_7', 'Son 7 gün'))}</option>`
    + `<option value="30"${days === '30' ? ' selected' : ''}>${esc(t('ui.chronic.period_30', 'Son 30 gün'))}</option></select></div>`;
}

export function sectionMarkup(payload = null) {
  const days = String(payload?.days || '7');
  const missing = payload?.note_codes?.includes('archive_missing');
  const mock = payload?.mock === true;
  const controls = missing || mock ? '' : controlsMarkup(days);
  const period = days === '30' ? esc(t('ui.chronic.period_30', 'Son 30 gün')) : esc(t('ui.chronic.period_7', 'Son 7 gün'));
  const statusText = mock ? esc(t('ui.chronic.mock', 'Örnek veri modunda bu bölüm gösterilmez.'))
    : missing ? esc(t('ui.chronic.archive_missing', "Bu sunucuda Nabız arşivi yok; kronik aksaklık hesaplanamadı."))
      : payload ? esc(t('ui.chronic.loaded', '{period}: {count} satır.', {
        period,
        count: int(payload.total_rows || 0),
      })) : esc(t('ui.chronic.loading', 'Arşiv okunuyor.'));
  const body = missing || mock || !payload ? '' : contentMarkup(payload);
  return `<section id="chronic" class="chronic" aria-labelledby="chronic-title">${titleAndDescription()}`
    + controls + `<p class="status-line" id="chronic-status" role="status" aria-live="polite">${statusText}</p>`
    + `<button type="button" id="chronic-retry" class="btn btn-quiet" hidden>${esc(t('ui.chronic.retry', 'Yeniden dene'))}</button>`
    + `<div class="chronic-body" id="chronic-body">${body}</div></section>`;
}

function ensureStylesheet(doc) {
  const found = [...doc.querySelectorAll('link[rel="stylesheet"]')]
    .some((link) => link.getAttribute('href') === STYLESHEET);
  if (found) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = STYLESHEET;
  doc.head.append(link);
}

function setBusy(section, busy) {
  const body = section.querySelector('#chronic-body');
  if (busy) body.setAttribute('aria-busy', 'true');
  else body.removeAttribute('aria-busy');
  const list = section.querySelector('#chronic-list');
  if (!list) return;
  if (busy) list.setAttribute('aria-busy', 'true');
  else list.removeAttribute('aria-busy');
}

export async function mountChronic(doc) {
  const marker = doc.querySelector(MARKER);
  const anchor = ANCHORS.map((selector) => doc.querySelector(selector)).find(Boolean);
  if (!marker || !anchor) return null;
  let language = 'tr';
  if (!MOCK) {
    const location = (doc.defaultView && doc.defaultView.location) || globalThis.location || { search: '' };
    if (new URLSearchParams(location.search).get('lang') === 'en') language = await loadCatalogs('en');
  }
  ensureStylesheet(doc);
  const section = doc.createElement('section');
  section.innerHTML = sectionMarkup(MOCK ? { mock: true } : null);
  anchor.after(section);
  const status = section.querySelector('#chronic-status');
  const controls = section.querySelector('.chronic-controls');
  const body = section.querySelector('#chronic-body');
  const retry = section.querySelector('#chronic-retry');
  let requestNumber = 0;
  let loading = false;
  let lastLoadedAt = 0;
  let pendingPayload = null;

  function setStatus(value, sourceLanguage = language) {
    status.innerHTML = value;
    status.lang = sourceLanguage;
  }

  async function load() {
    if (MOCK) return;
    const number = ++requestNumber;
    pendingPayload = null;
    const days = section.querySelector('#chronic-days').value;
    loading = true;
    retry.hidden = true;
    const oldCopy = section.querySelector('#chronic-copy');
    if (oldCopy) oldCopy.hidden = true;
    setBusy(section, true);
    setStatus(esc(t('ui.chronic.loading', 'Arşiv okunuyor.')));
    try {
      const payload = await get(PATH, { days });
      if (number !== requestNumber) return;
      if (payload.note_codes?.includes('archive_missing')) {
        applyPayload({ number, days, missing: true, payload });
      } else {
        applyPayload({ number, days, payload });
      }
    } catch (error) {
      if (number !== requestNumber) return;
      pendingPayload = null;
      setBusy(section, false);
      const prefix = esc(t('ui.chronic.failed', 'Liste şu an alınamadı: {message}', { message: '' })).trim();
      setStatus(`<span lang="${language}">${prefix}</span> <span lang="tr">${esc(error.message || '')}</span>`);
      retry.hidden = false;
    } finally {
      if (number === requestNumber) loading = false;
    }
  }

  function applyPayload(result) {
    if (body.contains(doc.activeElement)) {
      pendingPayload = result;
      return;
    }
    pendingPayload = null;
    if (result.number !== requestNumber) return;
    if (result.missing) {
      controls?.remove();
      body.innerHTML = '';
      setStatus(esc(t('ui.chronic.archive_missing', "Bu sunucuda Nabız arşivi yok; kronik aksaklık hesaplanamadı.")));
    } else {
      body.innerHTML = contentMarkup(result.payload);
      const period = result.days === '30'
        ? esc(t('ui.chronic.period_30', 'Son 30 gün')) : esc(t('ui.chronic.period_7', 'Son 7 gün'));
      setStatus(esc(t('ui.chronic.loaded', '{period}: {count} satır.', { period, count: int(result.payload.total_rows || 0) })));
      const copy = section.querySelector('#chronic-copy');
      copy?.addEventListener('click', () => copyVisible(result.payload));
    }
    setBusy(section, false);
    lastLoadedAt = Date.now();
  }

  async function copyVisible(payload) {
    const includeMore = Boolean(section.querySelector('.chronic-more')?.open);
    const value = copyText(payload, includeMore);
    const copyStatus = section.querySelector('#chronic-copy-status');
    const navigator = (doc.defaultView && doc.defaultView.navigator) || globalThis.navigator;
    try {
      if (!navigator?.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(value);
      copyStatus.textContent = t('ui.chronic.copied', 'Liste kopyalandı.');
      copyStatus.lang = language;
    } catch {
      let textarea = section.querySelector('#chronic-copy-fallback');
      if (!textarea) {
        textarea = doc.createElement('textarea');
        textarea.id = 'chronic-copy-fallback';
        textarea.className = 'chronic-copy-fallback';
        textarea.readOnly = true;
        textarea.setAttribute('aria-label', t('ui.chronic.copy_fallback', 'Metin seçildi; kopyalamak için kopyalayın.'));
        body.append(textarea);
      }
      textarea.value = value;
      textarea.hidden = false;
      textarea.focus();
      textarea.select();
      copyStatus.textContent = t('ui.chronic.copy_fallback', 'Metin seçildi; kopyalamak için kopyalayın.');
      copyStatus.lang = language;
    }
  }

  if (MOCK) return section;
  section.querySelector('#chronic-days').addEventListener('change', load);
  retry.addEventListener('click', load);
  body.addEventListener('focusout', (event) => {
    if (pendingPayload && !body.contains(event.relatedTarget)) applyPayload(pendingPayload);
  });
  doc.addEventListener('visibilitychange', () => {
    if (doc.visibilityState === 'visible' && !loading && !pendingPayload && Date.now() - lastLoadedAt >= STALE_MS) void load();
  });
  void load();
  return section;
}

if (typeof document !== 'undefined') void mountChronic(document);
