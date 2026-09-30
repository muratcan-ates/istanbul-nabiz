/* The example account screen's markup (DECISIONS #38). Pure: no DOM, no network, so node can test it.
 * Every provider card and every signed-in view carries the example band: no real İBB, İstanbulkart or
 * Google connection exists, and the page must never let anyone think otherwise. */

import { esc } from './format.js';
import { t } from './i18n_text.js';

const EXAMPLE_BAND = t('ui.acct.example_band', 'Örnek hesap · gerçek İBB/İstanbulkart bağlantısı yok · entegrasyon İBB izni gerektirir');

function bandMarkup() {
  return `<p class="acct-band" role="note"><span class="tag is-warn">${esc(t('ui.acct.example_tag', 'Örnek'))}</span> `
    + `${esc(t('ui.acct.example_band', 'Örnek hesap · gerçek İBB/İstanbulkart bağlantısı yok · entegrasyon İBB izni gerektirir'))}</p>`;
}

/** One sign-in card. The SMS flow shows its example code on the screen: no SMS is ever sent. */
function providerCard(provider, smsCode) {
  const key = esc(provider.key);
  const sms = provider.flow === 'sms'
    ? `<div class="field"><label for="acct-sms-${key}">${esc(t('ui.acct.sms_label', 'SMS kodu'))}</label>`
      + `<input id="acct-sms-${key}" name="sms_code" inputmode="numeric" autocomplete="off" maxlength="12">`
      + `<p class="field-hint">${esc(t('ui.acct.sms_hint', 'SMS gönderilmez. Örnek kod:'))} <b>${esc(smsCode)}</b>. ${esc(t('ui.acct.sms_phone_hint', 'Telefon numarası sorulmaz.'))}</p></div>`
    : '';
  const emailExample = t('ui.acct.email_placeholder', 'ornek@example.com');
  return `<form class="acct-card" data-provider="${key}" autocomplete="off">`
    + `<h3 lang="tr">${esc(provider.label)}</h3>${bandMarkup()}`
    + `<div class="field"><label for="acct-email-${key}">${esc(t('ui.acct.email_label', 'E-posta (örnek adres yazabilirsiniz)'))}</label>`
    + `<input id="acct-email-${key}" name="email" type="email" placeholder="${esc(emailExample)}" required></div>${sms}`
    + `<p class="field-hint">${esc(t('ui.acct.email_hint', 'Doğrulama e-postası gönderilmez; önizlemesi Profilim altında görünür.'))}</p>`
    + `<button type="submit" class="btn btn-primary" lang="tr">${esc(provider.label)}</button></form>`;
}

function tierTable(tiers, current) {
  const rows = (tiers || []).map((tier) => `<tr${tier.tier === current ? ' aria-current="true"' : ''}><th scope="row" lang="tr">${esc(tier.label)}</th>`
    + `<td>${esc(tier.questions)}</td><td>${esc(tier.model_calls)}</td></tr>`).join('');
  return `<div class="kvkk-table acct-tiers" role="region" aria-label="${esc(t('ui.acct.quota_aria', 'Günlük kota tablosu'))}" tabindex="0"><table>`
    + `<thead><tr><th scope="col">${esc(t('ui.acct.tier_heading', 'Katman'))}</th><th scope="col">${esc(t('ui.acct.daily_questions', 'Günlük soru'))}</th>`
    + `<th scope="col">${esc(t('ui.acct.daily_model_calls', 'Günlük model çağrısı'))}</th></tr></thead>`
    + `<tbody>${rows}</tbody></table></div>`
    + `<p class="field-hint">${esc(t('ui.acct.quota_closed', 'Kota dolunca cevaplar kural yoluyla (modelsiz) sürer. 153 yönlendirmesi kotaya hiç takılmaz.'))}</p>`;
}

function consentBlock(consent) {
  return '<label class="check acct-consent"><input type="checkbox" id="acct-consent">'
    + `<span><span class="check-label">${esc(t('ui.acct.consent_label', 'Açık rıza veriyorum.'))}</span><br><span class="field-hint"><span lang="tr">${esc(consent.text)}</span>`
    + ` (${esc(t('ui.acct.consent_version', 'metin sürümü'))} <span lang="tr">${esc(consent.version)}</span>) <a href="/kvkk.html#kvkk-hesap">${esc(t('ui.acct.kvkk_link', 'Ayrıntı: KVKK'))}</a></span></span></label>`
    + `<p class="field-error" id="acct-consent-error" hidden>${esc(t('ui.acct.consent_error', 'Hesap bağlamak için açık rıza kutusunu işaretleyin. Rıza yoksa hiçbir şey kaydedilmez.'))}</p>`;
}

function signedInView(view) {
  const account = view.account || {};
  return `${bandMarkup()}<dl class="acct-facts">`
    + `<dt>${esc(t('ui.acct.login', 'Giriş'))}</dt><dd lang="tr">${esc(account.provider_label)}</dd>`
    + `<dt>${esc(t('ui.acct.email', 'E-posta'))}</dt><dd>${esc(account.email)}</dd>`
    + `<dt>${esc(t('ui.acct.tier', 'Katman'))}</dt><dd lang="tr">${esc(account.tier)}</dd>`
    + `<dt>${esc(t('ui.acct.consent', 'Rıza'))}</dt><dd>${esc(account.consent_at)} (${esc(t('ui.acct.version', 'sürüm'))} <span lang="tr">${esc(account.consent_version)}</span>)</dd></dl>`
    + `<div class="btn-row"><button type="button" class="btn btn-danger" id="acct-delete">${esc(t('ui.acct.delete', 'Hesabımı ve verilerimi sil'))}</button></div>`
    + `<p class="field-hint">${esc(t('ui.acct.delete_hint', 'Sunucudaki hesap kaydı, takip konuları ve e-posta önizlemeleri ile bu tarayıcıdaki tüm Nabız verileri silinir.'))}</p>`;
}

function outboxList(previews) {
  if (!previews || !previews.length) return `<p class="field-hint">${esc(t('ui.acct.outbox_empty', 'Henüz hazırlanmış e-posta yok.'))}</p>`;
  return `<ul class="acct-outbox">${previews.map((preview) => `<li><details><summary lang="tr">${esc(preview.subject)}</summary>`
    + `<p class="field-hint" lang="tr">${esc(preview.note)}</p><pre lang="tr">${esc(preview.text)}</pre></details></li>`).join('')}</ul>`;
}

/** The quota strip's sentence, and its call to link an account when that would give more. */
function quotaParts(status) {
  if (!status || !Number.isFinite(Number(status.questions_limit))) return { text: '', cta: '', tier: '' };
  const left = t('ui.quota.left', 'Bugün kalan: {left}/{limit} soru', {
    left: status.questions_left, limit: status.questions_limit,
  });
  const link = t('ui.quota.link', 'daha fazlası için hesap bağla');
  if (status.questions_left <= 0 || status.model_open === false) {
    return {
      text: t('ui.quota.closed', '{left} · model kapalı, cevaplar kural yoluyla sürüyor · 153 her zaman açık', { left }),
      cta: status.has_account ? '' : link,
      tier: '',
    };
  }
  return status.has_account ? { text: left, cta: '', tier: status.tier_label || '' } : { text: left, cta: link, tier: '' };
}

function quotaText(status) {
  const { text, cta, tier } = quotaParts(status);
  const complete = tier ? `${text} · ${tier}` : text;
  return cta ? `${complete} · ${cta}` : complete;
}

export { EXAMPLE_BAND, bandMarkup, providerCard, tierTable, consentBlock, signedInView, outboxList, quotaParts, quotaText };
