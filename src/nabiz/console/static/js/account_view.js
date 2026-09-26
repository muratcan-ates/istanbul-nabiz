/* The example account screen's markup (DECISIONS #38). Pure: no DOM, no network, so node can test it.
 * Every provider card and every signed-in view carries the example band: no real İBB, İstanbulkart or
 * Google connection exists, and the page must never let anyone think otherwise. */

import { esc } from './format.js';

const EXAMPLE_BAND = 'Örnek hesap · gerçek İBB/İstanbulkart bağlantısı yok · entegrasyon İBB izni gerektirir';
const EMAIL_PLACEHOLDER = 'ornek@example.com';

function bandMarkup(text = EXAMPLE_BAND) {
  return `<p class="acct-band" role="note"><span class="tag is-warn">Örnek</span> ${esc(text)}</p>`;
}

/** One sign-in card. The SMS flow shows its example code on the screen: no SMS is ever sent. */
function providerCard(provider, smsCode) {
  const key = esc(provider.key);
  const sms = provider.flow === 'sms'
    ? `<div class="field"><label for="acct-sms-${key}">SMS kodu</label>`
      + `<input id="acct-sms-${key}" name="sms_code" inputmode="numeric" autocomplete="off" maxlength="12">`
      + `<p class="field-hint">SMS gönderilmez. Örnek kod: <b>${esc(smsCode)}</b>. Telefon numarası sorulmaz.</p></div>`
    : '';
  return `<form class="acct-card" data-provider="${key}" autocomplete="off">`
    + `<h3>${esc(provider.label)}</h3>${bandMarkup(provider.band || EXAMPLE_BAND)}`
    + `<div class="field"><label for="acct-email-${key}">E-posta (örnek adres yazabilirsiniz)</label>`
    + `<input id="acct-email-${key}" name="email" type="email" placeholder="${EMAIL_PLACEHOLDER}" required></div>${sms}`
    + '<p class="field-hint">Doğrulama e-postası gönderilmez; önizlemesi Profilim altında görünür.</p>'
    + `<button type="submit" class="btn btn-primary">${esc(provider.label)}</button></form>`;
}

function tierTable(tiers, current) {
  const rows = (tiers || []).map((t) => `<tr${t.tier === current ? ' aria-current="true"' : ''}><th scope="row">${esc(t.label)}</th>`
    + `<td>${esc(t.questions)}</td><td>${esc(t.model_calls)}</td></tr>`).join('');
  return '<div class="kvkk-table acct-tiers" role="region" aria-label="Günlük kota tablosu" tabindex="0"><table>'
    + '<thead><tr><th scope="col">Katman</th><th scope="col">Günlük soru</th><th scope="col">Günlük model çağrısı</th></tr></thead>'
    + `<tbody>${rows}</tbody></table></div>`
    + '<p class="field-hint">Kota dolunca cevaplar kural yoluyla (modelsiz) sürer. Acil durum (112) ve 153 yönlendirmesi kotaya hiç takılmaz.</p>';
}

function consentBlock(consent) {
  return '<label class="check acct-consent"><input type="checkbox" id="acct-consent">'
    + `<span><span class="check-label">Açık rıza veriyorum.</span><br><span class="field-hint">${esc(consent.text)}`
    + ` (metin sürümü ${esc(consent.version)}) <a href="/kvkk.html#kvkk-hesap">Ayrıntı: KVKK</a></span></span></label>`
    + '<p class="field-error" id="acct-consent-error" hidden>Hesap bağlamak için açık rıza kutusunu işaretleyin. Rıza yoksa hiçbir şey kaydedilmez.</p>';
}

function signedInView(view) {
  const account = view.account || {};
  return `${bandMarkup(view.band || EXAMPLE_BAND)}<dl class="acct-facts">`
    + `<dt>Giriş</dt><dd>${esc(account.provider_label)}</dd>`
    + `<dt>E-posta</dt><dd>${esc(account.email)}</dd>`
    + `<dt>Katman</dt><dd>${esc(account.tier)}</dd>`
    + `<dt>Rıza</dt><dd>${esc(account.consent_at)} (sürüm ${esc(account.consent_version)})</dd></dl>`
    + '<div class="btn-row"><button type="button" class="btn btn-danger" id="acct-delete">Hesabımı ve verilerimi sil</button></div>'
    + '<p class="field-hint">Sunucudaki hesap kaydı, takip konuları ve e-posta önizlemeleri ile bu tarayıcıdaki tüm Nabız verileri silinir.</p>';
}

function outboxList(previews) {
  if (!previews || !previews.length) return '<p class="field-hint">Henüz hazırlanmış e-posta yok.</p>';
  return `<ul class="acct-outbox">${previews.map((p) => `<li><details><summary>${esc(p.subject)}</summary>`
    + `<p class="field-hint">${esc(p.note)}</p><pre>${esc(p.text)}</pre></details></li>`).join('')}</ul>`;
}

/** The quota strip's sentence, and its call to link an account when that would give more. */
function quotaParts(status) {
  if (!status || !Number.isFinite(Number(status.questions_limit))) return { text: '', cta: '' };
  const left = `Bugün kalan: ${status.questions_left}/${status.questions_limit} soru`;
  if (status.questions_left <= 0 || status.model_open === false) {
    return {
      text: `${left} · model kapalı, cevaplar kural yoluyla sürüyor · acil 112 ve 153 her zaman açık`,
      cta: status.has_account ? '' : 'daha fazlası için hesap bağla',
    };
  }
  return status.has_account ? { text: `${left} · ${status.tier_label}`, cta: '' } : { text: left, cta: 'daha fazlası için hesap bağla' };
}

function quotaText(status) {
  const { text, cta } = quotaParts(status);
  return cta ? `${text} · ${cta}` : text;
}

export { EXAMPLE_BAND, bandMarkup, providerCard, tierTable, consentBlock, signedInView, outboxList, quotaParts, quotaText };
