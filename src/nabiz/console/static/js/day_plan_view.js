/* Pure markup for the event day plan. Browser state and dates are supplied by day_plan.js. */

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

const tr = (translate, key, fallback, vars = {}) => translate(key, fallback, vars);

export function addDays(value, amount) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + amount)).toISOString().slice(0, 10);
}

export function formatDate(value, lang) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return String(value || '');
  return new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(new Date(`${value}T12:00:00Z`));
}

export function formatStamp(value, lang) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || '');
  return new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

export function plannerMarkup() {
  return `<div class="dayplan-body">
    <p class="dayplan-intro" data-intro></p><p class="dayplan-status" role="status" aria-live="polite" data-status></p>
    <form class="dayplan-filters" data-filters>
      <div class="dayplan-date"><label for="dayplan-date" data-date-label></label><input id="dayplan-date" name="date" type="date" required></div>
      <div class="dayplan-filter-row">
        <div class="dayplan-district"><label for="dayplan-district" data-district-label></label><select id="dayplan-district" name="district"></select></div>
        <fieldset class="dayplan-audience"><legend data-audience-label></legend>
          <label><input type="radio" name="audience" value="all" checked><span data-audience-all></span></label>
          <label><input type="radio" name="audience" value="child"><span data-audience-child></span></label>
          <label><input type="radio" name="audience" value="adult"><span data-audience-adult></span></label>
        </fieldset>
        <div class="dayplan-checks"><label><input type="checkbox" name="free"><span data-free-label></span></label>
          <label><input type="checkbox" name="stepFree"><span data-stepfree-label></span></label></div>
      </div>
      <p class="dayplan-hint" data-filter-hint></p><button class="btn" type="submit" data-submit></button>
    </form>
    <ol class="dayplan-list" data-list hidden></ol><div class="dayplan-source" data-source hidden></div>
    <details class="dayplan-hidden" data-hidden hidden><summary data-hidden-title></summary><div data-hidden-body></div></details>
    <div class="dayplan-plans" data-plan-host></div></div>`;
}

export function routeFormHtml(plan, lang, translate, routeError, today) {
  if (!plan || plan.date < today) return '';
  const toField = routeError
    ? `<div class="dayplan-field"><label for="dayplan-to">${esc(tr(translate, 'ui.dayplan.to', 'Nereye'))}</label><input id="dayplan-to" name="to" value="${esc(plan.to || plan.event.venue)}"></div>` : '';
  return `<form class="dayplan-route-form" data-route lang="${lang}">
    <div class="dayplan-field"><label for="dayplan-from">${esc(tr(translate, 'ui.dayplan.from', 'Nereden'))}</label>
      <input id="dayplan-from" name="from" maxlength="120" value="${esc(plan.from || '')}" autocomplete="off">
      <p class="dayplan-hint">${esc(tr(translate, 'ui.dayplan.from_hint', 'Semt ya da durak adı yazın; ev adresi yazmayın. Bu cihazda kalır.'))}</p></div>
    ${toField}<button class="btn" type="submit" data-route-submit>${esc(tr(translate, 'ui.dayplan.add_trip', 'Ulaşımı ekle'))}</button>
    <p class="dayplan-route-status" data-route-status role="status" aria-live="polite"></p></form>`;
}

export function sourceFooterHtml(data, lang, translate, captured) {
  const stamp = data.source || {};
  const staleLine = stamp.stale
    ? `<p>${esc(tr(translate, 'ui.dayplan.stale', 'Etkinlik listesi {date} tarihinde alındı; güncel olmayabilir. Gitmeden önce etkinlik sayfasını kontrol edin.', { date: captured }))}</p>` : '';
  const license = stamp.license_note ? `<p lang="tr">${esc(stamp.license_note)}</p>` : '';
  return `<p lang="${lang}">${esc(tr(translate, 'ui.dayplan.source', 'Kaynak: kultur.istanbul · alındı {stamp}', { stamp: captured }))}</p>${staleLine}${license}`
    + `<p>${esc(tr(translate, 'ui.culture.disclaimer', 'Resmî İBB hizmeti değildir.'))}</p>`;
}

export function hiddenReasonHtml(counts, hasMissing, translate) {
  return `<p>${esc(tr(translate, 'ui.dayplan.hidden_counts', 'Geçmiş: {past}; iptal veya ertelendi: {cancelled}; başlamış: {started}; tarihsiz: {undated}; tarih çözülemedi: {unparsed}.', counts))}</p>`
    + (hasMissing ? `<p>${esc(tr(translate, 'ui.dayplan.not_captured', 'Kültür AŞ’nin tam etkinlik listesi JavaScript ile yükleniyor; Nabız yalnız ana sayfadaki tarihli etkinlikleri okuyabildi.'))}</p>` : '');
}

export function typeLabel(type, lang = 'tr') {
  const label = lang === 'en' && type.name_en ? type.name_en : type.name_tr || type.slug || '';
  const labelLang = lang === 'en' && type.name_en ? 'en' : 'tr';
  return `<span class="dayplan-tag" lang="${labelLang}">${esc(label)}</span>`;
}

export function eventCardHtml(event, lang, translate) {
  const labels = (event.types || []).map((item) => typeLabel(item, lang)).join('');
  const soldOutTag = event.sold_out && !(event.types || []).some((item) => item.slug === 'tukendi')
    ? `<span class="dayplan-tag">${esc(tr(translate, 'ui.dayplan.sold_out', 'Tükendi'))}</span>` : '';
  const sourceText = lang === 'en'
    ? `<p class="dayplan-source-language" lang="en">${esc(tr(translate, 'quote.source_is_turkish', 'Kaynak metin Türkçedir.'))}</p>` : '';
  const district = event.district
    ? `<p class="dayplan-meta">${esc(tr(translate, 'ui.dayplan.district_value', 'İlçe: {district}', { district: event.district }))}</p>`
    : `<p class="dayplan-meta">${esc(tr(translate, 'ui.dayplan.district_missing', 'İlçe kaynakta yok.'))}</p>`;
  const planButton = event.sold_out ? '' : `<button class="btn" type="button" data-plan-id="${esc(event.id)}">${esc(
    tr(translate, 'ui.dayplan.make_plan', 'Bununla plan kur'),
  )}</button>`;
  return `<li class="dayplan-event" data-event-id="${esc(event.id)}">
    <article>
      <h3 lang="tr">${esc(event.title)}</h3>
      ${sourceText}
      <p class="dayplan-meta" lang="tr">${esc(event.date_text)}</p>
      <p class="dayplan-meta" lang="tr">${esc(event.venue || tr(translate, 'ui.dayplan.venue_missing', 'Mekân kaynakta yok.'))}</p>
      ${district}
      <div class="dayplan-tags">${labels}${soldOutTag}</div>
      <p class="dayplan-meta">${esc(tr(translate, 'ui.dayplan.ticket_note', 'Kayıt ve bilet etkinlik sayfasındadır; Nabız kayıt yapmaz.'))}</p>
      <div class="dayplan-actions">
        <a class="btn btn-quiet" href="${esc(event.link)}" target="_blank" rel="noopener" lang="${lang}">${esc(
        tr(translate, 'ui.dayplan.event_page', 'Etkinlik sayfası (kultur.istanbul)')
  )}<svg aria-hidden="true" focusable="false"><use href="/icons.svg#external-link"></use></svg><span class="sr-only">${esc(tr(translate, 'ui.dayplan.new_tab', 'Yeni sekmede açılır.'))}</span></a>
        ${planButton}
      </div>
    </article>
  </li>`;
}

function tripLine(options, lang, translate) {
  const available = (options || []).filter((option) => option.available && option.minutes !== null && option.minutes !== undefined
    && Number.isFinite(Number(option.minutes)));
  if (!available.length) return tr(translate, 'ui.dayplan.no_comparison', 'Karşılaştırma yok.');
  return available.map((option) => {
    const mode = option.mode === 'bus' ? tr(translate, 'ui.dayplan.bus', 'Otobüs') : tr(translate, 'ui.dayplan.metro', 'Metro');
    const label = option.mode === 'bus' && option.line_code ? `${mode} ${option.line_code}` : mode;
    const minutes = Math.round(Number(option.minutes));
    const status = option.accessibility?.lift_status;
    const access = status === 'working' ? ` · ${tr(translate, 'ui.dayplan.lift_working', 'İBB kaydında arıza yok.')}`
      : status === 'out_of_service' ? ` · ${tr(translate, 'ui.dayplan.lift_out', 'Asansör arızalı (İBB kaydı).')}`
        : status === 'unknown' ? ` · ${tr(translate, 'ui.dayplan.lift_unknown', 'Asansör durumu doğrulanamadı.')}` : '';
    return `${label}: ${minutes} ${tr(translate, 'ui.dayplan.minutes', 'dk')}${access}`;
  }).join(' · ');
}

export function planSteps(plan, lang, translate, today) {
  if (!plan || plan.date < today || !plan.event) return [];
  const event = plan.event;
  const eventTime = event.time
    ? tr(translate, 'ui.dayplan.event_time', 'Saat: {time}', { time: event.time })
    : tr(translate, 'ui.dayplan.time_unknown', 'Saat kaynakta yok; etkinlik sayfasına bakın.');
  let hours = '';
  if (plan.venue_hours) {
    const recorded = plan.venue_hours;
    if (recorded.open_on_day === true) {
      hours = recorded.opens === '7/24'
        ? tr(translate, 'ui.dayplan.open_all_day', 'Kayda göre o gün 7/24 açık.')
        : tr(translate, 'ui.dayplan.open_hours', 'Kayda göre {opens} ile {closes} arası açık.', {
          opens: recorded.opens, closes: recorded.closes,
        });
    } else if (recorded.open_on_day === false) {
      hours = tr(translate, 'ui.dayplan.closed_day', 'E30 kaydına göre o gün kapalı.');
    } else {
      hours = tr(translate, 'ui.dayplan.no_hours', 'Çalışma saati kayıtta yok.');
    }
  } else hours = tr(translate, 'ui.dayplan.no_hours', 'Çalışma saati kayıtta yok.');
  let nearby = '';
  if (Array.isArray(plan.nearby) && plan.nearby.length) {
    nearby = plan.nearby.map((place) => {
      const kind = place.kind === 'museum' ? tr(translate, 'ui.culture.museum', 'Müze') : tr(translate, 'ui.culture.library', 'Kütüphane');
      return `${place.name} (${kind}), ${place.opens} ile ${place.closes} arası`;
    }).join('; ');
  } else if (!event.district) {
    nearby = tr(translate, 'ui.dayplan.nearby_unknown', 'İlçe kaynakta yok; yakındaki kütüphane ve müze önerilemedi.');
  } else {
    nearby = tr(translate, 'ui.dayplan.nearby_empty', 'Aynı ilçede o gün açık kayıt bulunamadı.');
  }
  return [
    { label: tr(translate, 'ui.dayplan.step_exit', 'Çıkış'), text: plan.from || tr(translate, 'ui.dayplan.from_missing', 'Semt ya da durak yazın.') },
    { label: tr(translate, 'ui.dayplan.step_out', 'Gidiş'), text: tripLine(plan.trip?.out, lang, translate) },
    { label: tr(translate, 'ui.dayplan.step_event', 'Etkinlik'), source: true, text: [event.date_text, eventTime, event.venue, hours].filter(Boolean).join(' · ') },
    ...(plan.nearby !== undefined || !event.district ? [{ label: tr(translate, 'ui.dayplan.step_nearby', 'Yakında'), source: true, text: nearby }] : []),
    { label: tr(translate, 'ui.dayplan.step_back', 'Dönüş'), text: tripLine(plan.trip?.back, lang, translate) },
  ];
}

export function planStepsHtml(plan, lang, translate, today) {
  const steps = planSteps(plan, lang, translate, today);
  return `<ol class="dayplan-steps">${steps.map((step, index) => {
    const sourceLanguage = step.source ? ' lang="tr"' : '';
    return `<li><span class="dayplan-number">${String(index + 1).padStart(2, '0')}</span><div><h4>${esc(step.label)}</h4><p${sourceLanguage}>${esc(step.text)}</p></div></li>`;
  }).join('')}</ol>`;
}

export function planPanelHtml(plan, lang, translate, today) {
  const date = plan.date;
  return `<section class="dayplan-panel" aria-labelledby="dayplan-panel-title">
    <h3 id="dayplan-panel-title" tabindex="-1">${esc(tr(translate, 'ui.dayplan.plan_title', 'Gün planınız'))}</h3>
    <p class="dayplan-saved">${esc(tr(translate, 'ui.dayplan.saved', 'Plan tarihi: {date} · Kaydedildi: {saved}', {
    date: plan.date_label || date, saved: plan.saved_label || plan.saved_at,
  }))}</p>
    <p class="dayplan-plan-status" data-plan-status role="status" aria-live="polite"></p>
    ${planStepsHtml(plan, lang, translate, today)}
    <p class="dayplan-estimate">${esc(tr(translate, 'ui.dayplan.estimate_note', 'Süreler bugünkü veriyle tahmindir; plan gününde değişebilir.'))}</p>
    ${(plan.venue_sources || []).map((source) => `<p class="dayplan-meta" lang="${lang}">${esc(tr(translate, 'ui.dayplan.venue_source', 'İBB Açık Veri · kayıt tarihi {recorded}', { recorded: source.resource_last_modified }))}</p>`).join('')}
    ${plan.holiday_note ? `<p class="dayplan-meta">${esc(tr(translate, 'ui.dayplan.holiday_note', 'Resmî tatil ve özel kapanışlar kayıtta yok; gitmeden önce arayın.'))}</p>` : ''}
    ${plan.event.sold_out ? `<p class="dayplan-meta">${esc(tr(translate, 'ui.dayplan.sold_out', 'Tükendi'))}</p>` : ''}
    <div class="dayplan-actions">
      <button class="btn btn-quiet" type="button" data-calendar>${esc(tr(translate, 'ui.dayplan.calendar', 'Takvime ekle'))}</button>
      <button class="btn btn-quiet" type="button" data-remove-plan>${esc(tr(translate, 'ui.dayplan.remove', 'Planı kaldır'))}</button>
    </div>
  </section>`;
}

export function pastPlanHtml(translate) {
  return `<section class="dayplan-panel" aria-labelledby="dayplan-panel-title"><h3 id="dayplan-panel-title" tabindex="-1">${esc(
    tr(translate, 'ui.dayplan.past_plan', 'Bu planın tarihi geçti.'),
  )}</h3><button class="btn btn-quiet" type="button" data-remove-plan>${esc(
    tr(translate, 'ui.dayplan.remove', 'Planı kaldır'),
  )}</button></section>`;
}
