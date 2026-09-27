/* Pure markup for the public poll card and its aggregate results. */

import { dateTime, esc } from './format.js';
import { currentLang, t } from './i18n_text.js';

function percentText(value, lang = currentLang()) {
  return lang === 'en' ? `${Number(value)}%` : `%${Number(value)}`;
}

function cardMarkup(poll, { preview = false } = {}) {
  const suffix = preview ? '-preview' : '';
  const title = `poll-title${suffix}`;
  const target = poll.target && poll.target.kind === 'district'
    ? `<p class="poll-target">${esc(t('ui.poll.district', 'Bu anket {district} için.', { district: poll.target.district }))}</p>` : '';
  const options = (poll.options || []).map((option) => (
    `<label class="poll-option"><input type="radio" name="poll-choice${suffix}" value="${esc(option.key)}">`
    + `<span lang="tr">${esc(option.label)}</span></label>`
  )).join('');
  const completed = preview
    ? `<p class="poll-preview-note">${esc(t('ui.poll.preview_note', 'Önizleme; henüz yayımlanmadı.'))}</p>` : '';
  const card = `<section class="poll-card" id="istanbula-sor${suffix}" aria-labelledby="${title}">`
    + `<h2 id="${title}">${esc(t('ui.poll.title', 'İstanbul\'a Sor'))}</h2>${target}`
    + `<form class="poll-form"><fieldset><legend lang="tr">${esc(poll.question)}</legend>${options}</fieldset>`
    + `<p class="field-error" data-poll-error hidden></p>`
    + `<div class="poll-actions"><button type="submit" class="btn" data-poll-vote>${esc(t('ui.poll.vote', 'Oy ver'))}</button>`
    + `<button type="button" class="btn btn-quiet" data-poll-dismiss>${esc(poll.target && poll.target.kind === 'district'
      ? t('ui.poll.dismiss_district', 'Bu ilçede değilim') : t('ui.poll.dismiss', 'Şimdi değil'))}</button></div></form>`
    + `<p class="status-line" role="status" aria-live="polite" data-poll-status></p>`
    + `<p class="poll-disclosure"><span class="tag is-warn">${esc(t('ui.poll.example', 'Örnek'))}</span> `
    + `${esc(t('ui.poll.disclosure', 'Simüle operatörün anketi; resmî İBB anketi değildir. Cihaz başına bir oy; seçiminiz bu cihazla ilişkilendirilmeden sayılır. Bitiş: {date}.', { date: dateTime(poll.closes_at) }))}</p>`
    + completed + '</section>';
  return preview ? `<div class="poll-preview" inert>${card}</div>` : card;
}

function resultsMarkup(result) {
  const rows = (result.rows || []).map((row) => {
    const share = row.percent === null || row.percent === undefined
      ? `<span>${esc(t('ui.poll.wait_for_five', '5 cevaptan sonra'))}</span>`
      : `<span>${esc(percentText(row.percent))}</span><span class="poll-bar" aria-hidden="true" style="--share: ${Number(row.percent)}%"></span>`;
    return `<tr><th scope="row" lang="tr">${esc(row.label)}</th><td>${Number(row.count)}</td>`
      + `<td data-label="${esc(t('ui.poll.share', 'Pay'))}">${share}</td></tr>`;
  }).join('');
  return '<table class="poll-results"><caption>' + esc(t('ui.poll.results', 'Sonuçlar')) + '</caption>'
    + `<thead><tr><th scope="col">${esc(t('ui.poll.option', 'Seçenek'))}</th>`
    + `<th scope="col">${esc(t('ui.poll.votes', 'Cevap'))}</th><th scope="col">${esc(t('ui.poll.share', 'Pay'))}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>`;
}

export { cardMarkup, percentText, resultsMarkup };
