/* İBB Açık Veri: which datasets İBB publishes, searched in the server's copy of the portal's catalogue
 * (GET /api/datasets). Nothing is asked until the visitor types a subject or picks a category, and
 * every result names its publisher, formats and last update, links to the dataset's page on
 * data.ibb.gov.tr, and says how old the catalogue copy is. Without a copy the server's own sentence
 * is shown as it is. The stylesheet loads with the section, like the service-status band. */

import { get } from './api.js';
import { dateTime, esc } from './format.js';
import { icon } from './icons.js';

const CATEGORIES = [
  'Bilgi ve İletişim Teknolojileri', 'Enerji', 'Ekonomi', 'Güvenlik', 'Mobilite', 'Çevre', 'İnsan', 'Yönetişim', 'Yaşam',
];
const LIMIT = 8;
const HINT = 'Bir konu yazın (örnek: otopark, baraj, wifi) ya da bir kategori seçin.';

function addStylesheet(doc) {
  if (doc.querySelector('link[data-open-data-styles]')) return;
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/css/open_data.css';
  link.dataset.openDataStyles = 'true';
  doc.head.append(link);
}

function day(iso) {
  return iso ? dateTime(iso) : 'tarih yok';
}

function datasetCard(hit) {
  const meta = [hit.organization, (hit.categories || []).join(', ')].filter(Boolean).join(' · ');
  const formats = (hit.formats || []).map((format) => `<span class="tag">${esc(format)}</span>`).join('');
  const api = hit.datastore ? '<span class="tag is-info">Veri API\'si var</span>' : '';
  const summary = hit.summary ? `<p class="od-summary">${esc(hit.summary)}</p>` : '';
  return `<li class="od-card">
    <h3 class="od-title"><a href="${esc(hit.url)}" target="_blank" rel="noopener noreferrer">${esc(hit.title)}${icon('external-link')}</a></h3>
    ${meta ? `<p class="od-meta">${esc(meta)}</p>` : ''}
    ${summary}
    <p class="od-tags">${formats}${api}<span class="od-updated">son güncelleme ${esc(day(hit.last_updated))}</span></p>
  </li>`;
}

function headline(body) {
  const copy = `katalog kaydı ${day(body.catalog && body.catalog.captured_at_utc)}`;
  const synthetic = body.catalog && body.catalog.synthetic ? ' <span class="tag is-warn">sentetik test kaydı</span>' : '';
  const within = body.category ? `${esc(body.category)} kategorisinde ` : '';
  let lead;
  if (!body.count) lead = `${within}eşleşme yok`;
  else if (body.mode === 'search') lead = `${within}${body.total_matches} eşleşme, ilk ${body.count} tanesi`;
  else if (body.mode === 'category') lead = `${esc(body.category)} kategorisinde ${body.total_matches} veri seti, en son güncellenenler`;
  else lead = 'En son güncellenen veri setleri';
  return `<p class="od-head">${lead} · ${esc(copy)}${synthetic}</p>`;
}

function render(result, body) {
  if (!body.datasets || !body.datasets.length) {
    result.innerHTML = `${headline(body)}<p class="od-empty">${esc(body.note || 'Eşleşen veri seti bulunamadı.')}</p>`;
    return;
  }
  result.innerHTML = `${headline(body)}<ul class="od-list">${body.datasets.map(datasetCard).join('')}</ul>`
    + '<p class="od-foot">Kaynak: İBB Açık Veri Portalı (data.ibb.gov.tr), İBB Açık Veri Lisansı.</p>';
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
  chips.innerHTML = CATEGORIES.map((name) => (
    `<button type="button" class="chip" data-category="${esc(name)}" aria-pressed="false">${esc(name)}</button>`
  )).join('');
  result.innerHTML = `<p class="od-empty">${HINT}</p>`;

  async function search() {
    const q = input.value.trim();
    if (!q && !category) {
      result.innerHTML = `<p class="od-empty">${HINT}</p>`;
      return;
    }
    if (controller) controller.abort();
    controller = new AbortController();
    result.setAttribute('aria-busy', 'true');
    result.innerHTML = '<p class="od-empty">Katalogda aranıyor…</p>';
    try {
      render(result, await get('/api/datasets', { q, category, limit: LIMIT }, controller.signal));
    } catch (err) {
      if (err.name === 'AbortError') return;
      result.innerHTML = `<p class="od-empty" role="alert">${esc(err.message)}</p>`;
    } finally {
      result.setAttribute('aria-busy', 'false');
    }
  }

  form.addEventListener('submit', (event) => { event.preventDefault(); search(); });
  chips.addEventListener('click', (event) => {
    const chip = event.target.closest('button[data-category]');
    if (!chip) return;
    category = category === chip.dataset.category ? '' : chip.dataset.category;
    chips.querySelectorAll('button[data-category]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.category === category));
    });
    search();
  });
}

mountOpenData(document);

export { mountOpenData, datasetCard, CATEGORIES };
