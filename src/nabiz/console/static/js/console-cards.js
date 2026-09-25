/* The operator page's renderers: the stat strip, the queue, the decision card, the trace, rule
 * drafts. Status is always icon, word and colour together. Pure (no DOM). */

import { UNKNOWN, clock, dateTime, esc, int, num, shortAge } from './format.js';
import { icon } from './icons.js';
import { citations, stamp } from './provenance.js';

const SEVERITY_TR = { info: 'bilgi', warning: 'uyarı', critical: 'kritik' };
const SEVERITY_ICON = { info: 'info-circle', warning: 'alert-triangle', critical: 'alert-triangle' };
const PATH_TR = { reflex: 'refleks', arena: 'arena' };
const PATH_ICON = { reflex: 'bolt', arena: 'arrows-exchange' };
const STATUS_TR = {
  closed_by_reflex: 'refleksle kapandı', awaiting_approval: 'onay bekliyor', approved: 'onaylandı', rejected: 'reddedildi',
  deferred: 'ertelendi',
};
const KIND_TR = {
  metro_equipment: 'Metro ekipmanı', metro_status: 'Metro hattı', arrival: 'varış', traffic: 'trafik', air: 'hava kalitesi',
  parking: 'otopark', alternative: 'adımsız alternatif', equipment_fault: 'ekipman arızası', long_outage: 'uzun süren arıza',
  hub_faults: 'aktarma merkezinde arızalar', source_stale: 'bayat kaynak', parking_full: 'otopark doluluğu',
  air_quality: 'hava kalitesi', bus_bunching: 'otobüs yığılması',
};
/* Settled: nothing left to decide. A deferred card is not settled: it can still be decided. */
const SETTLED = ['approved', 'rejected', 'closed_by_reflex'];
const STEP_TR = {
  signal_received: 'sinyal', routed: 'yönlendirme', reflex_closed: 'refleks', reflex_failed: 'refleks çalışamadı',
  arena_drafted: 'Arena kartı', approval: 'karar', rule_adopted: 'kural benimsendi', rule_revoked: 'kural geri alındı',
};
const STANCE_TR = { support: 'destekliyor', oppose: 'karşı çıkıyor', conditional: 'şartlı destekliyor' };
const STANCE_ICON = { support: 'circle-check', oppose: 'alert-triangle', conditional: 'clock-question' };
const LEVEL_TR = { high: 'yüksek', medium: 'orta', low: 'düşük' };
const ACTION_TR = {
  publish_card: 'vatandaş kartını güncelle',
  publish_alternative: 'onaylı alternatifi yayımla',
  maintenance_request: 'bakım talebi taslağı (simüle)',
  hold: 'beklet ve doğrula',
  none: 'hiçbir şey yapma',
};

const word = (table, key) => table[key] || key || UNKNOWN;

/* ---- stats ------------------------------------------------------------------------------- */
function tile(value, label, glyph, isWord) {
  return `<li class="stat"><span class="stat-value${isWord ? ' is-word' : ''}">${value}</span>`
    + `<span class="stat-label">${icon(glyph)}${label}</span></li>`;
}

function seconds(value) {
  return Number.isFinite(value) ? { text: esc(shortAge(value)), isWord: false } : { text: 'henüz yok', isWord: true };
}

function statsStrip(stats) {
  const median = seconds(stats.median_decision_s);
  const latency = seconds(stats.citizen_update_latency_s);
  const rate = Number.isFinite(stats.approval_rate) ? { text: `%${num(stats.approval_rate * 100, 0)}`, isWord: false }
    : { text: 'henüz yok', isWord: true };
  const stamp = stats.rubber_stamp_warning
    ? `<li class="stat"><span class="tag is-warn">${icon('alert-triangle')}göstermelik onay uyarısı</span>`
      + '<span class="stat-label">son kararların neredeyse hepsi onay: kanıt gerçekten okunuyor mu?</span></li>'
    : '';
  return tile(int(stats.reflex_closed_today), 'bugün refleksle kapanan', 'bolt')
    + tile(int(stats.awaiting_approval), 'onay bekleyen', 'clock-pause')
    + tile(int(stats.deferred), 'ertelenen (karar bekliyor)', 'clock-question')
    + tile(median.text, 'medyan karar süresi', 'gauge', median.isWord)
    + tile(latency.text, 'vatandaş sayfasına yansıma süresi', 'trending-up', latency.isWord)
    + tile(rate.text, 'onay oranı', 'circle-check', rate.isWord)
    + stamp;
}

/* ---- queue ------------------------------------------------------------------------------- */
function queueItem(item, current) {
  const sev = SEVERITY_TR[item.severity] ? item.severity : 'info';
  const path = PATH_TR[item.path] ? item.path : 'arena';
  return `<li><button type="button" class="queue-item is-${sev}" data-id="${esc(item.signal_id)}" aria-current="${current ? 'true' : 'false'}">`
    + `<span class="queue-sev">${icon(SEVERITY_ICON[sev])}</span>`
    + `<span class="queue-head"><span class="queue-title">${esc(item.title)}</span>`
    + `<span class="tag ${path === 'reflex' ? '' : 'is-info'}">${icon(PATH_ICON[path])}${PATH_TR[path]}</span></span>`
    + `<span class="queue-meta"><span>${SEVERITY_TR[sev]}</span><span>${esc(word(KIND_TR, item.kind))}</span>`
    + `<span>${esc(word(STATUS_TR, item.status))}</span><span>${clock(item.created_at)}</span></span>`
    + `<span class="queue-summary">${esc(item.summary || '')}</span></button></li>`;
}

function queueLists(items, currentId) {
  const arena = items.filter((i) => i.path !== 'reflex');
  const reflex = items.filter((i) => i.path === 'reflex');
  return {
    arena: arena.length ? arena.map((i) => queueItem(i, i.signal_id === currentId)).join('') : '',
    reflex: reflex.length ? reflex.map((i) => queueItem(i, i.signal_id === currentId)).join('') : '',
    arenaCount: arena.length,
    reflexCount: reflex.length,
    awaiting: arena.filter((i) => i.status === 'awaiting_approval' || i.status === 'deferred').length,
  };
}

/* ---- decision card ----------------------------------------------------------------------- */
function evidenceList(evidence, freshnessWarnS) {
  if (!evidence || !evidence.length) return '<p class="section-note">Kanıt yok: bu karar kanıtsız onaylanamaz.</p>';
  return `<ol class="evidence">${evidence.map((e) => {
    const old = e.provenance && Number.isFinite(e.provenance.age_s) && e.provenance.age_s > freshnessWarnS;
    return `<li class="evidence-item"><span>${esc(e.text)}</span><span>${stamp(e.provenance)}`
      + `${old ? ` <span class="tag is-warn">${icon('history')}eşikten eski</span>` : ''}</span></li>`;
  }).join('')}</ol>`;
}

function opinionList(opinions) {
  if (!opinions || !opinions.length) return '<p class="section-note">Görüş yok.</p>';
  return `<ul class="opinions">${opinions.map((o) => {
    const stance = STANCE_TR[o.stance] ? o.stance : 'conditional';
    return `<li class="opinion is-${stance}"><span class="opinion-role">${esc(o.role)}</span>`
      + `<span class="opinion-stance">${icon(STANCE_ICON[stance])}${STANCE_TR[stance]}</span>`
      + `<p class="opinion-text">${esc(o.rationale)}</p>${citations(o.citations)}</li>`;
  }).join('')}</ul>`;
}

function freshnessLine(freshnessS, warnS) {
  if (!Number.isFinite(freshnessS)) return `<span class="decision-fresh is-warn">${icon('clock-question')}veri tazeliği bilinmiyor</span>`;
  const old = freshnessS > warnS;
  return `<span class="decision-fresh${old ? ' is-warn' : ''}">${icon(old ? 'history' : 'clock')}veri tazeliği ${esc(shortAge(freshnessS))}`
    + `${old ? ' (eşikten eski)' : ''}</span>`;
}

function decisionCard(d, options) {
  const warnS = (options && options.freshnessWarnS) || 900;
  const s = d.signal || {};
  const sev = SEVERITY_TR[s.severity] ? s.severity : 'info';
  const done = SETTLED.includes(s.status);
  const conf = d.confidence || {};
  const level = LEVEL_TR[conf.level] ? conf.level : 'low';
  const action = d.proposed_action || {};
  const ruleBased = d.author === 'kural';
  return `<div class="decision-part">
  <div class="decision-head"><h3 id="decision-signal">${esc(s.title || d.signal_id)}</h3>`
    + `<span class="tag ${sev === 'critical' ? 'is-bad' : sev === 'warning' ? 'is-warn' : ''}">${icon(SEVERITY_ICON[sev])}${SEVERITY_TR[sev]}</span>`
    + `<span class="tag">${esc(word(STATUS_TR, s.status))}</span></div>
  <p>${esc(s.summary || '')}</p>
  <div class="decision-meta"><span>${esc(d.signal_id)}</span><span>${esc(word(KIND_TR, s.kind))}</span>`
    + `<span>${s.created_at ? dateTime(s.created_at) : ''}</span>${freshnessLine(d.freshness_s, warnS)}</div>
</div>
${d.dissent_summary ? `<div class="decision-part"><div class="callout callout-warn">${icon('alert-triangle')}<div>`
    + `<p class="callout-title">İtiraz özeti</p><p>${esc(d.dissent_summary)}</p></div></div></div>` : ''}
<div class="decision-part">
  <details id="evidence" class="decision-evidence">
    <summary>${icon('chevron-right')}Kanıt (${(d.evidence || []).length})</summary>
    ${evidenceList(d.evidence, warnS)}
  </details>
  <p class="actions-gate" id="evidence-gate"${done ? ' hidden' : ''}>Onaylamadan önce kanıtı açın.</p>
</div>
<div class="decision-part">
  <h4>Seçenekler</h4>
  ${d.alternatives && d.alternatives.length
    ? `<ol class="alts">${d.alternatives.map((a) => `<li><b>${esc(a.label)}</b>${esc(a.detail || '')}</li>`).join('')}</ol>`
    : '<p class="section-note">Seçenek listesi yok.</p>'}
</div>
<div class="decision-part">
  <div class="decision-head"><h4>Üç koltuğun görüşü</h4>`
    + `${ruleBased ? `<span class="tag">${icon('list-details')}Koltuklar kural tabanlı (model yok)</span>` : `<span class="tag">görüşleri yazan: ${esc(d.author || UNKNOWN)}</span>`}</div>
  ${opinionList(d.opinions)}
</div>
<div class="decision-part">
  <h4>Önerilen eylem</h4>
  <div class="proposed"><p><b>${esc(word(ACTION_TR, action.kind))}</b></p><p>${esc(action.text || '')}</p>`
    + `<p class="field-hint">Son geçerlilik: ${action.expires_at ? dateTime(action.expires_at) : 'belirtilmedi'}. Uygulanan tek şey Nabız yüzündeki metindir; dışarıya hiçbir şey gönderilmez.</p></div>
  <div class="confidence is-${level}"><span class="confidence-level">${icon(level === 'high' ? 'circle-check' : level === 'medium' ? 'clock-question' : 'alert-triangle')}güven: ${LEVEL_TR[level]}</span>`
    + `${conf.reasons && conf.reasons.length ? `<ul>${conf.reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}</div>
</div>
<div class="decision-part actions" id="decision-actions"${done ? ' hidden' : ''}>
  <div class="field"><label for="decision-reason">Gerekçe</label>
    <textarea id="decision-reason" rows="3" maxlength="280" aria-describedby="reason-hint"></textarea>
    <span class="field-hint" id="reason-hint">Ret ve erteleme için zorunlu, en fazla 280 karakter. Kişi adı yazmayın.</span>
    <span class="field-error" id="reason-error" hidden>Ret ve erteleme için gerekçe yazın.</span></div>
  <div class="field" id="edit-field" hidden><label for="decision-edit">Düzenlenmiş metin</label>
    <textarea id="decision-edit" rows="4" maxlength="600" aria-describedby="edit-hint">${esc(action.text || '')}</textarea>
    <span class="field-hint" id="edit-hint">En fazla 600 karakter.</span></div>
  <div class="btn-row">
    <button type="button" class="btn btn-primary" data-act="approve" aria-disabled="true" aria-describedby="evidence-gate">${icon('circle-check')}Onayla</button>
    <button type="button" class="btn" data-act="edit">Düzenle</button>
    <button type="button" class="btn btn-danger" data-act="reject">Gerekçeli reddet</button>
    <button type="button" class="btn" data-act="defer">${icon('clock-pause')}Ertele</button>
  </div>
</div>
<div class="decision-part">
  <p class="status-line" id="decision-status" role="status"></p>
  <div class="btn-row"><button type="button" class="btn" data-act="trace">${icon('history')}Bu karar nasıl verildi?</button></div>
  <div id="trace"></div>
</div>`;
}

/* ---- trace and ledger -------------------------------------------------------------------- */
function hashBadge(ok) {
  return ok
    ? `<span class="tag is-ok">${icon('shield-lock')}zincir doğrulandı</span>`
    : `<span class="tag is-bad">${icon('alert-triangle')}zincir doğrulanamadı</span>`;
}

function traceList(trace) {
  const steps = trace.steps || [];
  return `<div class="decision-head"><h4>Adımlar (${steps.length})</h4>${hashBadge(trace.hash_ok === true)}</div>`
    + (steps.length ? `<ol class="trace">${steps.map((st) => `<li class="trace-step"><span class="trace-at">${dateTime(st.at)}</span>`
      + `<span><span class="trace-actor">${esc(st.actor)}</span> <span class="trace-kind">${esc(word(STEP_TR, st.kind))}</span></span>`
      + `<span>${esc(st.detail || '')}</span></li>`).join('')}</ol>` : '<p class="section-note">Defterde bu sinyal için kayıt yok.</p>');
}

function verifyBadge(v) {
  if (!v) return `<span class="tag is-warn">${icon('clock-question')}defter okunamadı</span>`;
  return v.ok
    ? `<span class="tag is-ok">${icon('shield-lock')}defter doğrulandı · ${int(v.entries)} kayıt</span>`
    : `<span class="tag is-bad">${icon('alert-triangle')}defter doğrulanamadı · ${int(v.entries)} kayıt</span>`;
}

/* ---- rule drafts ------------------------------------------------------------------------- */
function draftItem(d) {
  const id = esc(d.draft_id);
  const evidence = d.evidence_decisions || [];
  return `<li class="draft"><div class="draft-head"><h3>${esc(d.pattern)}</h3><span class="tag">${icon('bolt')}taslak ${id}</span></div>
  <p class="draft-evidence">Dayanak: ${evidence.length} onaylı karar (${evidence.map(esc).join(', ') || 'yok'}). Tek olaydan kural doğmaz.</p>
  <details><summary>${icon('chevron-right')}Kural taslağı (TOML)</summary><pre>${esc(d.proposed_rule_toml || '')}</pre></details>
  <form class="draft-form" data-id="${id}">
    <div class="field"><label for="days-${id}">Süre (gün)</label><input type="number" id="days-${id}" name="days" min="1" max="365" value="${Number(d.expires_days) || 30}"></div>
    <div class="field"><label for="reason-${id}">Gerekçe</label><input type="text" id="reason-${id}" name="reason" maxlength="280" required></div>
    <button type="submit" class="btn btn-primary">Benimse</button>
    <p class="field-hint">Benimsenen kural süreli çalışır, süresi dolunca kendiliğinden yenilenmez ve geri alınabilir.</p>
  </form></li>`;
}

export {
  SETTLED, SEVERITY_TR, STATUS_TR, STANCE_TR, LEVEL_TR, ACTION_TR, statsStrip, queueItem, queueLists, decisionCard, traceList, verifyBadge, draftItem,
};
