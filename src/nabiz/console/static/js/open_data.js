/* İBB Açık Veri: which datasets İBB publishes, searched in the server's copy of the portal's catalogue
 * (GET /api/datasets). Nothing is asked until the visitor types a subject or picks a category, and
 * every result names its publisher, formats and last update, links to the dataset's page on
 * data.ibb.gov.tr, and says how old the catalogue copy is. Without a copy the server's own sentence
 * is shown as it is. The stylesheet loads with the section, like the service-status band. Labels follow
 * the page language (i18n_text.js); dataset titles and summaries are İBB's data and stay Turkish. */

import { get } from './api.js';
import { currentLang, onLang, t } from './i18n_text.js';
import { dateTime, esc } from './format.js';
import { icon } from './icons.js';

const CATEGORIES = [
  'Bilgi ve İletişim Teknolojileri', 'Enerji', 'Ekonomi', 'Güvenlik', 'Mobilite', 'Çevre', 'İnsan', 'Yönetişim', 'Yaşam',
];
const LIMIT = 8;

function addStylesheet(doc) {
  if (doc.querySelector('link[data-open-data-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/open_data.css';
  link.dataset.openDataStyles = 'true';
  doc.head.append(link);
}

function day(iso) {
  return iso ? dateTime(iso) : t('ui.od.no_date', 'tarih yok');
}

function categoryLabel(name) {
  const index = CATEGORIES.indexOf(name);
  if (index === 0) return t('ui.od.cat.ict', 'Bilgi ve İletişim Teknolojileri');
  if (index === 1) return t('ui.od.cat.energy', 'Enerji');
  if (index === 2) return t('ui.od.cat.economy', 'Ekonomi');
  if (index === 3) return t('ui.od.cat.safety', 'Güvenlik');
  if (index === 4) return t('ui.od.cat.mobility', 'Mobilite');
  if (index === 5) return t('ui.od.cat.environment', 'Çevre');
  if (index === 6) return t('ui.od.cat.people', 'İnsan');
  if (index === 7) return t('ui.od.cat.governance', 'Yönetişim');
  if (index === 8) return t('ui.od.cat.life', 'Yaşam');
  return name;
}

function datasetCard(hit) {
  const meta = [hit.organization, (hit.categories || []).join(', ')].filter(Boolean).join(' · ');
  const formats = (hit.formats || []).map((format) => `<span class="tag">${esc(format)}</span>`).join('');
  const api = hit.datastore
    ? `<span class="tag is-info" lang="${currentLang()}">${esc(t('ui.od.api', 'Veri API\'si var'))}</span>` : '';
  const summary = hit.summary ? `<p class="od-summary" lang="tr">${esc(hit.summary)}</p>` : '';
  const updated = t('ui.od.updated', 'son güncelleme {day}', { day: day(hit.last_updated) });
  return `<li class="od-card" lang="tr">
    <h3 class="od-title"><a href="${esc(hit.url)}" target="_blank" rel="noopener noreferrer">${esc(hit.title)}${icon('external-link')}</a></h3>
    ${meta ? `<p class="od-meta" lang="tr">${esc(meta)}</p>` : ''}
    ${summary}
    <p class="od-tags">${formats}${api}<span class="od-updated" lang="${currentLang()}">${esc(updated)}</span></p>
  </li>`;
}

function headline(body) {
  const copy = t('ui.od.catalog_record', 'katalog kaydı {day}', { day: day(body.catalog && body.catalog.captured_at_utc) });
  const synthetic = body.catalog && body.catalog.synthetic
    ? ` <span class="tag is-warn" lang="${currentLang()}">${esc(t('ui.od.synthetic', 'sentetik test kaydı'))}</span>` : '';
  const category = body.category ? categoryLabel(body.category) : '';
  const within = category ? `${esc(t('ui.od.category_prefix', '{category} kategorisinde', { category }))} ` : '';
  let lead;
  if (!body.count) lead = `${within}${esc(t('ui.od.none', 'eşleşme yok'))}`;
  else if (body.mode === 'search') {
    lead = `${within}${esc(t('ui.od.matches', '{total} eşleşme, ilk {count} tanesi', {
      total: body.total_matches, count: body.count,
    }))}`;
  } else if (body.mode === 'category') {
    lead = esc(t('ui.od.category_count', '{category} kategorisinde {total} veri seti, en son güncellenenler', {
      category, total: body.total_matches,
    }));
  } else lead = esc(t('ui.od.latest', 'En son güncellenen veri setleri'));
  return `<p class="od-head" lang="${currentLang()}">${lead} · ${esc(copy)}${synthetic}</p>`;
}

function render(result, body) {
  if (!body.datasets || !body.datasets.length) {
    const note = body.note
      ? `<p class="od-empty" lang="tr">${esc(body.note)}</p>`
      : `<p class="od-empty" lang="${currentLang()}">${esc(t('ui.od.empty', 'Eşleşen veri seti bulunamadı.'))}</p>`;
    result.innerHTML = `${headline(body)}${note}`;
    return;
  }
  result.innerHTML = `${headline(body)}<ul class="od-list">${body.datasets.map(datasetCard).join('')}</ul>`
    + `<p class="od-foot" lang="${currentLang()}">${esc(t('ui.od.source', 'Kaynak: İBB Açık Veri Portalı (data.ibb.gov.tr), İBB Açık Veri Lisansı.'))}</p>`;
}

function mountOpenData(doc) {
  const form = doc.getElementById('acik-veri-form');
  const input = doc.getElementById('acik-veri-q');
  const chips = doc.getElementById('acik-veri-chips');
  const result = doc.getElementById('acik-veri-result');
  if (!form || !input || !chips || !result) return;
  addStylesheet(doc);
  let category = '';
  let controller = null;
  let lastView = { kind: 'hint' };

  function drawChips() {
    chips.innerHTML = CATEGORIES.map((name) => (
      `<button type="button" class="chip" data-category="${esc(name)}" aria-pressed="${String(name === category)}">${esc(categoryLabel(name))}</button>`
    )).join('');
  }

  function drawResult() {
    if (lastView.kind === 'hint') result.innerHTML = `<p class="od-empty" lang="${currentLang()}">${esc(t('ui.od.hint', 'Bir konu yazın (örnek: otopark, baraj, wifi) ya da bir kategori seçin.'))}</p>`;
    else if (lastView.kind === 'loading') result.innerHTML = `<p class="od-empty" lang="${currentLang()}">${esc(t('ui.od.loading', 'Katalogda aranıyor…'))}</p>`;
    else if (lastView.kind === 'error') result.innerHTML = `<p class="od-empty" role="alert" lang="tr">${esc(lastView.message)}</p>`;
    else render(result, lastView.body);
  }

  drawChips();
  drawResult();

  async function search() {
    const q = input.value.trim();
    if (!q && !category) {
      lastView = { kind: 'hint' };
      drawResult();
      return;
    }
    if (controller) controller.abort();
    controller = new AbortController();
    result.setAttribute('aria-busy', 'true');
    lastView = { kind: 'loading' };
    drawResult();
    try {
      lastView = { kind: 'results', body: await get('/api/datasets', { q, category, limit: LIMIT }, controller.signal) };
      drawResult();
    } catch (err) {
      if (err.name === 'AbortError') return;
      lastView = { kind: 'error', message: err.message };
      drawResult();
    } finally {
      result.setAttribute('aria-busy', 'false');
    }
  }

  form.addEventListener('submit', (event) => { event.preventDefault(); search(); });
  chips.addEventListener('click', (event) => {
    const chip = event.target.closest('button[data-category]');
    if (!chip) return;
    category = category === chip.dataset.category ? '' : chip.dataset.category;
    drawChips();
    search();
  });
  onLang(() => { drawChips(); drawResult(); });
}

if (typeof document !== 'undefined') mountOpenData(document);

export { mountOpenData, datasetCard, CATEGORIES, categoryLabel, render };
