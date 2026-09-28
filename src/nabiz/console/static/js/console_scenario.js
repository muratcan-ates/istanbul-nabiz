/* The intervention scenario section mounts after the citizen request queue. */
import { get, post, del, MOCK } from './api.js';
import { esc, dateTime } from './format.js';
import { t, onLang } from './i18n_text.js';

const PATH = '/api/console/scenario';
const STYLESHEET = '/css/console_scenario.css';
// Literal t() calls (P00 D2a): the page's catalogue check reads each key beside its Turkish.
const ASSUMPTIONS = {
  hypothetical: () => t('ui.scn.assume.hypothetical', 'Kapanış bir varsayımdır; İBB kaydına eklenmez ve kimseye bildirilmez.'),
  endpoints_only: () => t('ui.scn.assume.endpoints', 'Asansör yalnız binilen, inilen ve aktarma yapılan istasyonlarda sayılır; trenle geçilen istasyon etkilenmez.'),
  same_record: () => t('ui.scn.assume.record', 'Önce ve senaryo hesabı aynı İBB kaydıyla yapılır.'),
  not_traffic: () => t('ui.scn.assume.traffic', 'Sayılar güzergâh ve kayıt sayısıdır; yolcu, kalabalık ya da talep tahmini değildir.'),
  model_times: () => t('ui.scn.assume.times', 'Ek süreler istasyon mesafesi modelinden gelir; tarife içermez.'),
  saved_scope: () => t('ui.scn.assume.saved', 'Yalnız hesabıyla ve rızasıyla sunucuda kaydedilmiş yolculuklar sayılır; cihazdaki kayıtlar görünmez.'),
  small_hidden: () => t('ui.scn.assume.small', '3’ten az kayıt içeren sayılar gizlenir.'),
};

function parseRoutes(text) {
  const rows = String(text || '').split(/\r?\n/).map((line, index) => ({ line: line.trim(), number: index + 1 })).filter((row) => row.line);
  const errors = [];
  if (rows.length > 12) errors.push({ line: 13, message: t('ui.scn.routes.limit', 'En çok 12 güzergâh yazın.') });
  rows.forEach((row) => { if ((row.line.match(/>/g) || []).length !== 1) errors.push({ line: row.number, message: t('ui.scn.routes.format', 'Güzergâhı Başlangıç > Varış biçiminde yazın.') }); });
  return { routes: rows.slice(0, 12).map((row) => row.line), errors };
}

function summaryLine(result) {
  const counts = result?.counts || {};
  return t('ui.scn.summary', 'Senaryo: {station} istasyonunda asansör kapalı (varsayım). {total} güzergâhın {affected} tanesi etkilenir; {blocked} güzergâhta adımsız yol kalmaz, {detour} alternatifle sürer.', {
    station: result?.closure?.station || '', total: counts.total || 0, affected: counts.affected || 0,
    blocked: counts.blocked || 0, detour: counts.detour || 0,
  });
}

function rowModel(route) {
  const labels = {
    blocked: [() => t('ui.scn.effect.blocked', 'Adımsız yol kalmaz'), 'warn'],
    detour: [() => t('ui.scn.effect.detour', 'Alternatifle sürer'), 'accent'],
    not_affected: [() => t('ui.scn.effect.none', 'Etkilenmiyor'), 'quiet'],
    already_unavailable: [() => t('ui.scn.effect.before', 'Senaryodan önce de yok'), 'quiet'],
    unverified: [() => t('ui.scn.effect.unknown', 'Doğrulanamadı'), 'quiet'],
    invalid: [() => t('ui.scn.effect.invalid', 'Geçersiz güzergâh'), 'quiet'],
  };
  const [effect, tone] = labels[route?.effect] || labels.unverified;
  let after = effect();
  if (route?.effect === 'detour' && route.after?.alternative?.station) {
    after = t('ui.scn.after.detour', '{station} üzerinden', { station: route.after.alternative.station });
    if (Number.isFinite(route.added_minutes)) after += `, ${t('ui.scn.after.minutes', 'yaklaşık {minutes} dk ek', { minutes: route.added_minutes })}`;
  } else if (route?.effect === 'blocked') {
    after = route.after?.reason || after;
  }
  return {
    label: route?.label || `${route?.from || ''} > ${route?.to || ''}`,
    before: route?.before?.available ? t('ui.scn.before.available', 'adımsız yol var')
      : route?.effect === 'already_unavailable' ? t('ui.scn.before.unavailable', 'adımsız yol yok') : t('ui.scn.before.unknown', 'doğrulanamadı'),
    after, effectText: effect(), tone, sample: Boolean(route?.sample),
  };
}

function savedLine(saved) {
  const considered = typeof saved === 'string' ? saved : saved?.considered;
  if (!saved || saved.status === 'missing') return t('ui.scn.saved.missing', 'Kayıtlı yolculuk modülü bu sunucuda yok.');
  if (saved.status === 'no_table') return t('ui.scn.saved.no_table', 'Bu sunucuda kayıtlı yolculuk tablosu yok.');
  if (saved.status === 'consent_scope') return t('ui.scn.saved.consent', 'Kayıtlı yolculuk rızası bu kullanımı henüz kapsamıyor.');
  if (considered === null) return t('ui.scn.saved.not_counted', 'Kayıtlı yolculuklar bu senaryoda sayılmadı.');
  if (considered === 'lt3') return t('ui.scn.saved.lt3', '3’ten az kayıt etkileniyor.');
  return t('ui.scn.saved.count', '{count} kayıt etkileniyor.', { count: considered || 0 });
}

function assumptionLines(keys) {
  return (keys || []).filter((key) => ASSUMPTIONS[key]).map((key) => ASSUMPTIONS[key]());
}

function addStylesheet(doc) {
  if (doc.head.querySelector(`link[href="${STYLESHEET}"]`)) return;
  const link = doc.createElement('link'); link.rel = 'stylesheet'; link.href = STYLESHEET; doc.head.append(link);
}

function mountScenario(doc = globalThis.document) {
  if (!doc?.getElementById || doc.getElementById('scenario')) return null;
  const anchor = doc.getElementById('scenario-mount') || doc.getElementById('citizen-requests') || doc.getElementById('day');
  if (!anchor) return null;
  const section = doc.createElement('section'); section.id = 'scenario'; section.className = 'scenario';
  section.setAttribute('aria-labelledby', 'scenario-title'); anchor.after(section); addStylesheet(doc);
  const state = { stations: [], items: [], current: null, savedStatus: 'missing', station: '', line: '', routeText: '', includeSaved: false, sample: false, busy: false, message: '' };
  const $ = (selector) => section.querySelector(selector);

  function rowsMarkup(routes, effects) {
    return routes.map((route) => {
      const row = rowModel(route);
      const sample = row.sample ? `<span class="scenario-sample">${esc(t('ui.scn.sample', 'Örnek'))}</span>` : '';
      const before = route.before?.reason && !route.before.available ? `<span lang="tr">${esc(route.before.reason)}</span>` : esc(row.before);
      return `<tr><th scope="row" lang="tr">${esc(row.label)} ${sample}</th><td data-label="${esc(t('ui.scn.col.before', 'Önce'))}">${before}</td><td data-label="${esc(t('ui.scn.col.after', 'Senaryoda'))}" lang="tr">${esc(row.after)}</td><td data-label="${esc(t('ui.scn.col.effect', 'Durum'))}"><span class="scenario-badge is-${row.tone}">${esc(row.effectText)}</span></td></tr>`;
    }).join('');
  }

  function renderResult(result) {
    if (!result) return '';
    const counts = result.counts || {};
    const impacted = (result.routes || []).filter((route) => ['blocked', 'detour'].includes(route.effect));
    const quiet = (result.routes || []).filter((route) => !['blocked', 'detour'].includes(route.effect));
    const unaffected = quiet.filter((route) => route.effect === 'not_affected');
    const uncertain = quiet.filter((route) => ['unverified', 'already_unavailable', 'invalid'].includes(route.effect));
    const assumptions = assumptionLines(result.assumptions).map((line) => `<li>${esc(line)}</li>`).join('');
    const source = result.provenance || {};
    const stamp = source.observed_at ? t('ui.scn.source.stamp', 'Kayıtlı · {time}', { time: dateTime(source.observed_at) }) : t('ui.scn.source.unknown', 'Kayıt zamanı doğrulanamadı.');
    const sourceLink = source.url ? `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(t('ui.scn.source.open', 'İBB kaydını aç'))}</a>` : '';
    const saved = result.saved || {};
    const savedMarkup = saved.status === 'ok' && saved.considered !== null ? `<p>${esc(savedLine(saved))}</p><p class="scenario-note">${esc(t('ui.scn.saved.note', 'Yalnız bu sunucuda hesabıyla ve rızasıyla kaydedilmiş yolculuklar sayılır; cihazda tutulan kayıtlar görünmez. Bu sayı kişi sayısı değildir.'))}</p>`
      : `<p class="scenario-note">${esc(savedLine(saved))}</p>`;
    const specialDetails = uncertain.length ? `<details><summary>${esc(t('ui.scn.special.title', 'Doğrulanamayan veya senaryodan önce de olmayan güzergâhlar ({count})', { count: uncertain.length }))}</summary><table><caption>${esc(t('ui.scn.special.caption', 'Güzergâh durumu'))}</caption><thead><tr><th scope="col">${esc(t('ui.scn.col.route', 'Güzergâh'))}</th><th scope="col">${esc(t('ui.scn.col.effect', 'Durum'))}</th></tr></thead><tbody>${uncertain.map((route) => { const row = rowModel(route); return `<tr><th scope="row" lang="tr">${esc(row.label)}</th><td data-label="${esc(t('ui.scn.col.effect', 'Durum'))}"><span class="scenario-badge is-${row.tone}">${esc(row.effectText)}</span></td></tr>`; }).join('')}</tbody></table></details>` : '';
    const unaffectedDetails = unaffected.length ? `<p>${esc(t('ui.scn.unaffected.count', '{count} güzergâh etkilenmiyor.', { count: unaffected.length }))}</p><details><summary>${esc(t('ui.scn.unaffected.more', 'Etkilenmeyen güzergâhlar ({count})', { count: unaffected.length }))}</summary><ul>${unaffected.map((route) => `<li lang="tr">${esc(route.label)}</li>`).join('')}</ul></details>` : '';
    return `<div class="scenario-result"><h3>${esc(summaryLine(result))}</h3>${result.closure?.already_faulty ? `<p class="scenario-note">${esc(t('ui.scn.closure.faulty', 'Bu istasyon İBB kaydında zaten arızalı; senaryo bugünkü durumu gösterir.'))}</p>` : ''}${result.closure?.no_lift_record ? `<p class="scenario-note">${esc(t('ui.scn.closure.no_lift', 'İBB kaydında bu istasyon için asansör bilgisi yok; senaryo anlamlı değil.'))}</p>` : ''}<div class="scenario-assumptions"><h4>${esc(t('ui.scn.assumptions', 'Varsayımlar'))}</h4><ul>${assumptions}</ul></div>${impacted.length ? `<table class="scenario-routes"><caption>${esc(t('ui.scn.affected.caption', 'Etkilenen güzergâhlar'))}</caption><thead><tr><th scope="col">${esc(t('ui.scn.col.route', 'Güzergâh'))}</th><th scope="col">${esc(t('ui.scn.col.before', 'Önce'))}</th><th scope="col">${esc(t('ui.scn.col.after', 'Senaryoda'))}</th><th scope="col">${esc(t('ui.scn.col.effect', 'Durum'))}</th></tr></thead><tbody>${rowsMarkup(impacted)}</tbody></table>` : `<p>${esc(t('ui.scn.none.affected', 'Etkilenen güzergâh yok.'))}</p>`}${specialDetails}${unaffectedDetails}${savedMarkup}<p class="scenario-source">${esc(t('ui.scn.source.label', 'İBB metro arızalı ekipman kaydı'))} · ${esc(stamp)} ${sourceLink}</p><p class="scenario-note">${esc(t('ui.scn.model.label', 'İstasyon ve süre modeli: Nabız planlayıcısı (tahmin, tarife değil).'))}</p><details><summary>${esc(t('ui.scn.how.title', 'Nasıl hesaplandı?'))}</summary><ul><li>${esc(t('ui.scn.how.max', 'Operatör en çok 12 güzergâh girebilir.'))}</li><li>${esc(t('ui.scn.how.minimum', '3’ten az kayıt içeren toplamlar gizlenir.'))}</li><li>${esc(t('ui.scn.how.endpoints', 'Asansörler yalnız binilen, inilen ve aktarma istasyonlarında denetlenir.'))}</li></ul><p lang="tr">${esc(result.disclaimer || '')}</p></details></div>`;
  }

  function renderSaved() {
    const entries = state.items.map((item) => `<li><span lang="tr">${esc(item.station)}</span> · ${esc(item.line || t('ui.scn.all_lines', 'Tüm hatlar'))} · ${esc(t('ui.scn.saved.at', 'hesaplandı · {time}', { time: dateTime(item.created_at) }))} · ${esc(t('ui.scn.saved.affected', '{count} etkilenen', { count: item.counts?.affected || 0 }))}<button type="button" class="btn btn-quiet" data-open="${esc(item.id)}">${esc(t('ui.scn.open', 'Aç'))}</button><button type="button" class="btn btn-quiet" data-delete="${esc(item.id)}">${esc(t('ui.scn.delete', 'Sil'))}</button></li>`).join('');
    return `<details class="scenario-saved"><summary>${esc(t('ui.scn.saved.title', 'Kaydedilen senaryolar'))}</summary>${entries ? `<ul>${entries}</ul>` : `<p>${esc(t('ui.scn.saved.empty', 'Henüz kaydedilen senaryo yok.'))}</p>`}</details>`;
  }

  function render() {
    const activeId = doc.activeElement?.id || '';
    const lines = state.stations.find((item) => item.name === state.station)?.lines || [];
    const options = lines.map((line) => `<option value="${esc(line)}">${esc(line)}</option>`).join('');
    const stationOptions = state.stations.map((item) => `<option value="${esc(item.name)}">`).join('');
    const unavailable = state.savedStatus !== 'ok';
    const savedReason = savedLine({ status: state.savedStatus });
    const status = MOCK ? t('ui.scn.mock', 'Örnek veri modunda senaryo hesaplanmaz.') : state.message;
    section.setAttribute('aria-busy', state.busy ? 'true' : 'false');
    section.innerHTML = `<h2 id="scenario-title">${esc(t('ui.scn.title', 'Müdahale senaryosu'))}</h2><p class="scenario-description">${esc(t('ui.scn.description', 'Bir istasyonun asansörü kapanırsa hangi güzergâhların adımsız yolu değişir? Varsayımsal hesaptır; yolcu ya da trafik tahmini değildir.'))}</p><p class="scenario-note">${esc(t('ui.scn.disclaimer', 'Nabız simüle operatör aracı; resmî İBB planlama aracı değildir.'))}</p><p class="status-line" id="scenario-status" role="status" aria-live="polite">${esc(status || '')}</p><form id="scenario-form"><label for="scenario-station">${esc(t('ui.scn.station', 'İstasyon'))}</label><input id="scenario-station" list="scenario-stations" maxlength="60" value="${esc(state.station)}" required><datalist id="scenario-stations">${stationOptions}</datalist><label for="scenario-line">${esc(t('ui.scn.line', 'Hat'))}</label><select id="scenario-line"><option value="">${esc(t('ui.scn.all_lines', 'Tüm hatlar'))}</option>${options}</select><label for="scenario-routes">${esc(t('ui.scn.routes', 'Güzergâhlar'))}</label><textarea id="scenario-routes" rows="5" aria-describedby="scenario-routes-hint scenario-route-error">${esc(state.routeText)}</textarea><p class="field-hint" id="scenario-routes-hint">${esc(t('ui.scn.routes.hint', 'Her satıra bir güzergâh: Başlangıç > Varış (en çok 12)'))}</p><p class="field-error" id="scenario-route-error">${esc(state.routeError || '')}</p><label class="scenario-consent"><input id="scenario-include-saved" type="checkbox"${state.includeSaved ? ' checked' : ''}${unavailable ? ' disabled' : ''}>${esc(t('ui.scn.saved.toggle', 'Kayıtlı yolculukları da say (yalnız toplam sayı)'))}</label>${unavailable ? `<p class="field-hint">${esc(savedReason)}</p>` : ''}<div class="scenario-actions"><button type="submit" class="btn btn-primary"${state.busy || MOCK ? ' disabled' : ''}>${esc(t('ui.scn.calculate', 'Senaryoyu hesapla'))}</button><button type="button" class="btn btn-quiet" data-sample>${esc(t('ui.scn.sample.fill', 'Örnek listeyi doldur'))}</button></div></form>${state.current ? renderResult(state.current) : ''}${renderSaved()}`;
    const station = $('#scenario-station'); const line = $('#scenario-line');
    if (station) station.addEventListener('change', () => { state.station = station.value; state.line = ''; render(); });
    if (line) line.value = state.line;
    if (activeId) $(`#${activeId}`)?.focus();
  }

  section.addEventListener('input', (event) => {
    if (event.target.id === 'scenario-station') { state.station = event.target.value; state.line = ''; }
    if (event.target.id === 'scenario-routes') { state.routeText = event.target.value; state.sample = false; }
    if (event.target.id === 'scenario-include-saved') state.includeSaved = event.target.checked;
  });
  section.addEventListener('change', (event) => { if (event.target.id === 'scenario-line') state.line = event.target.value; });
  section.addEventListener('click', async (event) => {
    const sample = event.target.closest('[data-sample]');
    if (sample) { state.station = 'Zeytinburnu'; state.line = state.stations.find((item) => item.name === 'Zeytinburnu')?.lines?.includes('M1A') ? 'M1A' : ''; state.routeText = ['Zeytinburnu > Bağcılar', 'Bostancı > Kartal', 'Maltepe > Pendik'].join('\n'); state.sample = true; render(); return; }
    const open = event.target.closest('[data-open]');
    if (open) { try { state.current = await get(`${PATH}/${encodeURIComponent(open.dataset.open)}`); state.message = t('ui.scn.saved.opened', 'Kayıtlı sonuç: {time}. İBB kaydı o andaki haliyle.', { time: dateTime(state.current.computed_at) }); render(); } catch (error) { state.message = error.message; render(); } return; }
    const remove = event.target.closest('[data-delete]');
    if (remove) { try { await del(`${PATH}/${encodeURIComponent(remove.dataset.delete)}`); if (state.current?.id === remove.dataset.delete) state.current = null; const saved = await get(PATH); state.items = saved.items || []; render(); } catch (error) { state.message = error.message; render(); } }
  });
  section.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.busy || MOCK) return;
    const parsed = parseRoutes($('#scenario-routes')?.value || '');
    if (parsed.errors.length || !parsed.routes.length) { state.routeError = parsed.errors[0]?.message || t('ui.scn.routes.required', 'En az bir güzergâh yazın.'); render(); return; }
    state.station = $('#scenario-station')?.value || ''; state.line = $('#scenario-line')?.value || '';
    state.includeSaved = Boolean($('#scenario-include-saved')?.checked); state.busy = true; state.message = t('ui.scn.loading', 'Senaryo hesaplanıyor.'); render();
    try {
      state.current = await post(`${PATH}/run`, { station: state.station, line: state.line || null, routes: parsed.routes, include_saved: state.includeSaved, sample: state.sample });
      state.message = t('ui.scn.done', 'Senaryo kaydedildi.');
      const saved = await get(PATH); state.items = saved.items || []; state.savedStatus = saved.saved_status || state.savedStatus;
    } catch (error) { state.message = error.message; }
    state.busy = false; state.routeError = ''; render();
  });
  onLang(() => render());
  render();
  if (!MOCK) {
    state.busy = true; state.message = t('ui.scn.stations.loading', 'İstasyonlar yükleniyor.'); render();
    Promise.all([get(`${PATH}/stations`), get(PATH)]).then(async ([stationData, savedData]) => {
      state.stations = stationData.stations || []; state.items = savedData.items || []; state.savedStatus = savedData.saved_status || 'missing';
      if (state.items[0]) { try { state.current = await get(`${PATH}/${encodeURIComponent(state.items[0].id)}`); } catch { state.current = null; } }
      state.busy = false; state.message = ''; render();
    }).catch((error) => { state.busy = false; state.message = error.message; render(); });
  }
  return section;
}

if (typeof document !== 'undefined') mountScenario(document);
export { parseRoutes, summaryLine, rowModel, savedLine, assumptionLines, mountScenario };
