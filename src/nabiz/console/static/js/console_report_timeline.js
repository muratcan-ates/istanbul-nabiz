/* E66: the operator may move a report only along the server's transition table. */

import { MOCK, get, post } from './api.js';
import { esc } from './format.js';

const OPERATOR_MOVES = {
  recorded: ['reviewing'],
  reviewing: ['info_needed', 'referred', 'resolution_reported'],
  info_needed: ['reviewing'],
  referred: ['reviewing', 'resolution_reported'],
  reopened: ['reviewing'],
};
const LABELS = {
  tr: {
    title: 'Bildirim takibi', code: 'Kod', station: 'İstasyon', kind: 'Tür', stage: 'Nabız durumu', waiting: 'Yanıt beklenen', updated: 'Son değişiklik',
    stages: { recorded: 'Kaydedildi', reviewing: 'İnceleniyor', info_needed: 'Bilgi bekleniyor', referred: 'Yönlendirildi', resolution_reported: 'Çözüm bildirildi', confirmed: 'Sizin teyidiniz', reopened: 'Yeniden açıldı' },
    moves: { reviewing: 'İncelemeye al', info_needed: 'Bilgi iste', referred: 'Kuruma yönlendir', resolution_reported: 'Çözüm bildir', confirmed: 'Teyit et' },
    waitingOn: { operator: 'Simüle operatör', citizen: 'Vatandaş', agency: 'Kurum', none: 'Kimse' },
    history: 'Geçmiş', operator: 'Simüle operatör', citizen: 'Vatandaş yazdı (maskeli)', note: 'Not', noteVisible: 'Vatandaş bu notu görür.', agency: 'Kurum', choose: 'Kurum seçin', send: 'Geçişi kaydet', empty: 'Son 30 günde vatandaş bildirimi yok.', loading: 'Bildirimler yükleniyor.', error: 'Bildirimler yüklenemedi. Yeniden deneyin.', retry: 'Yeniden dene', reopened: 'Yeniden açıldı',
  },
  en: {
    title: 'Report tracking', code: 'Code', station: 'Station', kind: 'Type', stage: 'Nabız status', waiting: 'Waiting for', updated: 'Last change',
    stages: { recorded: 'Recorded', reviewing: 'In review', info_needed: 'More information needed', referred: 'Referred', resolution_reported: 'Resolution reported', confirmed: 'Your confirmation', reopened: 'Reopened' },
    moves: { reviewing: 'Start review', info_needed: 'Request information', referred: 'Refer to agency', resolution_reported: 'Report resolution', confirmed: 'Confirm' },
    waitingOn: { operator: 'Simulated operator', citizen: 'Citizen', agency: 'Agency', none: 'No one' },
    history: 'History', operator: 'Simulated operator', citizen: 'Citizen wrote (masked)', note: 'Note', noteVisible: 'The citizen will see this note.', agency: 'Agency', choose: 'Choose an agency', send: 'Save transition', empty: 'No citizen reports in the last 30 days.', loading: 'Loading reports.', error: 'Reports could not be loaded. Try again.', retry: 'Try again', reopened: 'Reopened',
  },
};

const escText = esc;

function safeTime(raw, locale) {
  const date = new Date(raw);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'tr-TR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

function movesFor(stage) {
  return [...(OPERATOR_MOVES[stage] || [])];
}

function historyMarkup(row, labels) {
  return '<ol class="rt-console-history">' + (row.history || []).map((event) => {
    const stage = labels.stages[event.stage] || event.stage;
    const actor = event.by === 'citizen' ? labels.citizen : event.by === 'operator' ? labels.operator : '';
    const note = event.note_masked || event.text_masked;
    return '<li><span>' + escText(stage) + '</span><time datetime="' + escText(event.at || '') + '">' + escText(safeTime(event.at, labels === LABELS.en ? 'en' : 'tr'))
      + '</time>' + (actor ? '<span>' + escText(actor) + '</span>' : '') + (note ? '<p>' + escText(note) + '</p>' : '') + '</li>';
  }).join('') + '</ol>';
}

function formMarkup(row, to, agencies, labels) {
  const noteRequired = ['info_needed', 'resolution_reported'].includes(to);
  const referred = to === 'referred';
  const note = noteRequired ? '<label for="rt-note-' + escText(row.code) + '">' + escText(labels.note) + '</label>'
    + '<textarea id="rt-note-' + escText(row.code) + '" name="note" minlength="5" maxlength="200" required></textarea><p>' + escText(labels.noteVisible) + '</p>' : '';
  const options = agencies.map((item) => '<option value="' + escText(item.id) + '">' + escText(item.name) + '</option>').join('');
  const agency = referred ? '<label for="rt-agency-' + escText(row.code) + '">' + escText(labels.agency) + '</label><select id="rt-agency-' + escText(row.code) + '" name="agency_id" required><option value="">' + escText(labels.choose) + '</option>' + options + '</select>' : '';
  return '<form class="rt-console-form" data-advance="' + escText(to) + '">' + note + agency
    + '<button class="btn btn-primary" type="submit">' + escText(labels.send) + '</button></form>';
}

function rowMarkup(row, expanded = false, agencies = [], locale = 'tr', formTo = null, error = '') {
  const labels = LABELS[locale] || LABELS.tr;
  const stage = labels.stages[row.stage] || row.stage;
  const status = row.stage === 'reopened' && row.reopen_count
    ? '<span class="tag is-warn">' + escText(labels.reopened) + ' · ' + escText(row.reopen_count) + '</span>' : escText(stage);
  const errorMarkup = error ? '<p class="rt-console-error" role="status">' + escText(error) + '</p>' : '';
  const detail = expanded ? '<tr class="rt-console-detail" id="rt-detail-' + escText(row.code) + '" data-detail="' + escText(row.code) + '"><td colspan="6"><div class="rt-console-detail-inner">'
    + '<h3>' + escText(labels.history) + '</h3>' + historyMarkup(row, labels)
    + (row.reopen_count ? '<p class="tag is-warn">' + escText(labels.reopened) + ' · ' + escText(row.reopen_count) + '</p>' : '')
    + errorMarkup + (formTo ? formMarkup(row, formTo, agencies, labels) : '<div class="rt-console-actions">'
      + movesFor(row.stage).map((to, index) => '<button class="btn' + (index === 0 ? ' btn-primary' : '') + '" type="button" data-advance-to="' + escText(to) + '">' + escText(labels.moves[to]) + '</button>').join('') + '</div>')
    + '</div></td></tr>' : '';
  return '<tr class="rt-console-row" data-code="' + escText(row.code) + '"><td><button class="rt-toggle" type="button" aria-expanded="' + (expanded ? 'true' : 'false') + '" aria-controls="rt-detail-' + escText(row.code) + '">' + escText(row.code) + '</button></td>'
    + '<td>' + escText(row.station || '') + '</td><td>' + escText(row.kind_text || '') + '</td><td class="rt-status-badge">' + status + '</td>'
    + '<td>' + escText(labels.waitingOn[row.waiting_on] || labels.waitingOn.none) + '</td><td>' + escText(safeTime(row.updated_at, locale)) + '</td></tr>' + detail;
}

function mount(doc) {
  if (!doc || MOCK) return null;
  const main = doc.querySelector('main');
  if (!main) return null;
  const host = doc.createElement('section');
  host.className = 'rt-console';
  host.id = 'report-timeline-console';
  host.setAttribute('aria-labelledby', 'rt-console-title');
  host.innerHTML = '<h2 id="rt-console-title">' + LABELS.tr.title + '</h2><p class="rt-console-status" role="status" aria-live="polite"></p>'
    + '<div class="rt-console-table-wrap"><table><thead><tr>'
    + ['code', 'station', 'kind', 'stage', 'waiting', 'updated'].map((key) => '<th scope="col">' + LABELS.tr[key] + '</th>').join('')
    + '</tr></thead><tbody></tbody></table></div>';
  const grid = doc.getElementById('report-timeline-mount') || doc.querySelector('.console-grid');
  if (grid) grid.after(host); else main.append(host);
  const state = { items: [], agencies: [], open: '', formTo: '', error: '', failed: false };
  const statusLine = host.querySelector('.rt-console-status');
  const tbody = host.querySelector('tbody');

  function render() {
    const locale = doc.documentElement.lang.toLowerCase().startsWith('en') ? 'en' : 'tr';
    const labels = LABELS[locale];
    host.querySelector('#rt-console-title').textContent = labels.title;
    [...host.querySelectorAll('thead th')].forEach((cell, index) => { cell.textContent = labels[['code', 'station', 'kind', 'stage', 'waiting', 'updated'][index]]; });
    tbody.innerHTML = state.items.length
      ? state.items.map((row) => rowMarkup(row, state.open === row.code, state.agencies, locale, state.formTo && state.open === row.code ? state.formTo : null, state.error)).join('')
      : '<tr><td colspan="6">' + escText(state.failed ? labels.error : labels.empty)
        + (state.failed ? ' <button class="btn btn-quiet" type="button" data-retry>' + escText(labels.retry) + '</button>' : '') + '</td></tr>';
  }

  async function load() {
    statusLine.textContent = LABELS[doc.documentElement.lang.startsWith('en') ? 'en' : 'tr'].loading;
    try {
      const result = await get('/api/console/report-timeline');
      state.items = result.items || [];
      state.agencies = result.agencies || [];
      state.failed = false;
      state.error = '';
      statusLine.textContent = state.items.length ? '' : LABELS[doc.documentElement.lang.startsWith('en') ? 'en' : 'tr'].empty;
    } catch (error) {
      state.failed = true;
      statusLine.textContent = LABELS[doc.documentElement.lang.startsWith('en') ? 'en' : 'tr'].error;
    }
    render();
  }

  async function advance(code, to, form) {
    const payload = { to };
    if (form?.elements.note) payload.note = form.elements.note.value.trim();
    if (form?.elements.agency_id) payload.agency_id = form.elements.agency_id.value;
    try {
      await post('/api/console/report-timeline/' + encodeURIComponent(code) + '/advance', payload);
      state.open = code;
      state.formTo = '';
      await load();
      const badge = host.querySelector('.rt-console-row[data-code="' + code + '"] .rt-status-badge');
      if (badge) badge.classList.add('is-updated');
      host.querySelector('.rt-toggle[aria-expanded="true"]')?.focus({ preventScroll: true });
    } catch (error) {
      state.error = error.message;
      render();
    }
  }

  host.addEventListener('click', (event) => {
    if (event.target.closest('[data-retry]')) { void load(); return; }
    const toggle = event.target.closest('.rt-toggle');
    if (toggle) {
      const code = toggle.closest('tr').dataset.code;
      state.open = state.open === code ? '' : code;
      state.formTo = '';
      state.error = '';
      render();
      host.querySelector('.rt-toggle[aria-expanded="true"]')?.focus({ preventScroll: true });
      return;
    }
    const button = event.target.closest('[data-advance-to]');
    if (!button) return;
    const row = state.items.find((item) => item.code === state.open);
    if (!row) return;
    const to = button.dataset.advanceTo;
    if (['info_needed', 'resolution_reported', 'referred'].includes(to)) {
      state.formTo = to;
      state.error = '';
      render();
      host.querySelector('textarea, select')?.focus({ preventScroll: true });
    } else void advance(row.code, to);
  });
  host.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-advance]');
    if (!form) return;
    event.preventDefault();
    void advance(state.open, form.dataset.advance, form);
  });
  host.addEventListener('animationend', (event) => event.target.classList.remove('is-updated'));
  doc.addEventListener('nabiz:decided', load);
  doc.addEventListener('nabiz:lang', render);
  void load();
  return { host, load, rowMarkup, movesFor };
}

function loadStyles(doc) {
  if (doc.querySelector('link[href="/css/console_report_timeline.css"]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/console_report_timeline.css';
  doc.head.append(link);
}

if (typeof document !== 'undefined') {
  loadStyles(document);
  mount(document);
}

export { rowMarkup, movesFor, mount };
