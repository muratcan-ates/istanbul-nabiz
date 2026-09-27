/* Pure markup for E52. Account data is explicitly escaped; this module has no page or network state. */
import { esc } from './format.js';
import { currentLang, t } from './i18n_text.js';

const CODE_ALPHABET = '23456789ADEFHJKMNPRTY';
const FAMILY_BAND = t(
  'ui.family.example_band',
  'Örnek aile · örnek hesaplarla çalışır · gerçek İBB ya da e-Devlet aile bağı kurulmaz · konum paylaşılmaz',
);

function normalizeCode(raw) {
  const code = String(raw || '').replace(/[\s-]/g, '').toUpperCase();
  return code.length === 6 && Array.from(code).every((char) => CODE_ALPHABET.includes(char)) ? code : null;
}

function formatCode(code) {
  return String(code || '').slice(0, 3) + ' ' + String(code || '').slice(3, 6);
}

function dateText(value) {
  const time = Date.parse(value || '');
  if (!Number.isFinite(time)) return esc(t('ui.family.unknown', 'bilinmiyor'));
  return new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'tr-TR', {
    timeZone: 'Europe/Istanbul', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(time);
}

function bandMarkup() {
  return '<p class="fam-band" role="note"><span class="tag is-warn">'
    + esc(t('ui.family.example_tag', 'Örnek')) + '</span> ' + esc(t('ui.family.example_band', FAMILY_BAND)) + '</p>';
}

function startView(consent) {
  const consentText = consent && consent.text ? consent.text : '';
  const consentVersion = consent && consent.version ? consent.version : '';
  return bandMarkup()
    + '<p class="fam-intro">' + esc(t('ui.family.intro', 'Aile kodu, onayladığınız en çok 5 kişiyle yalnız seçtiğiniz takip konularını ve durakları paylaşmanızı sağlar. Konum paylaşılmaz.')) + '</p>'
    + '<form class="fam-form" data-family-create>'
    + '<div class="field"><label for="family-display-name">' + esc(t('ui.family.display_name_label', 'Ailede görünecek adınız')) + '</label>'
    + '<input id="family-display-name" name="display_name" maxlength="24" autocomplete="nickname" required>'
    + '<p class="field-hint">' + esc(t('ui.family.display_name_hint', 'Örnek: Anne, Can. E-posta ya da telefon yazmayın.')) + '</p></div>'
    + '<label class="check fam-consent"><input type="checkbox" name="consent">'
    + '<span><span class="check-label">' + esc(t('ui.family.consent_label', 'Açık rıza veriyorum.')) + '</span><br>'
    + '<span class="field-hint" lang="tr">' + esc(consentText) + ' (' + esc(t('ui.family.consent_version', 'metin sürümü'))
    + ' <span lang="tr">' + esc(consentVersion) + '</span>) <a href="/kvkk.html#kvkk-hesap">'
    + esc(t('ui.family.kvkk_link', 'Ayrıntı: KVKK')) + '</a></span></span></label>'
    + '<p class="field-error fam-consent-error" hidden>' + esc(t('ui.family.consent_error', 'Açık rıza vermeden aile kodu oluşturulamaz. Hiçbir şey kaydedilmedi.')) + '</p>'
    + '<button type="submit" class="btn btn-primary">' + esc(t('ui.family.create_code', 'Aile kodu oluştur')) + '</button></form>'
    + '<details class="fam-join"><summary>' + esc(t('ui.family.join_summary', 'Aile koduyla katıl')) + '</summary>'
    + '<form class="fam-form fam-join-form" data-family-join><div class="field"><label for="family-join-code">'
    + esc(t('ui.family.join_code_label', 'Aile kodu')) + '</label><input id="family-join-code" name="code" autocomplete="off" '
    + 'autocapitalize="characters" spellcheck="false" maxlength="8" required><p class="field-hint">'
    + esc(t('ui.family.join_code_hint', '6 karakter; boşluk ve küçük harf sorun değil.')) + '</p><p class="field-error fam-code-error" hidden>'
    + esc(t('ui.family.code_format_error', 'Kod 6 geçerli harf ya da rakamdan oluşmalı.')) + '</p></div>'
    + '<div class="field"><label for="family-join-name">' + esc(t('ui.family.display_name_label', 'Ailede görünecek adınız'))
    + '</label><input id="family-join-name" name="display_name" maxlength="24" autocomplete="nickname" required></div>'
    + '<label class="check fam-consent"><input type="checkbox" name="consent"><span><span class="check-label">'
    + esc(t('ui.family.consent_label', 'Açık rıza veriyorum.')) + '</span><br><span class="field-hint" lang="tr">'
    + esc(consentText) + ' (' + esc(t('ui.family.consent_version', 'metin sürümü')) + ' <span lang="tr">'
    + esc(consentVersion) + '</span>) <a href="/kvkk.html#kvkk-hesap">'
    + esc(t('ui.family.kvkk_link', 'Ayrıntı: KVKK')) + '</a></span></span></label>'
    + '<p class="field-error fam-consent-error" hidden>' + esc(t('ui.family.join_consent_error', 'Açık rıza vermeden katılma isteği gönderilemez. Hiçbir şey kaydedilmedi.')) + '</p>'
    + '<button type="submit" class="btn">' + esc(t('ui.family.request_join', 'Katılma isteği gönder')) + '</button></form></details>'
    + '<p class="field-hint fam-demo-hint">' + esc(t('ui.family.demo_hint', 'Denemek için ikinci bir örnek hesabı başka bir tarayıcıda ya da gizli pencerede açabilirsiniz.')) + '</p>';
}

function pendingView(pending) {
  return bandMarkup() + '<div class="fam-pending"><h3>' + esc(t('ui.family.pending_title', 'Katılma isteğiniz bekliyor')) + '</h3>'
    + '<p>' + esc(t('ui.family.pending_intro', 'Katılma isteğiniz kod sahibinin onayını bekliyor.')) + '</p>'
    + '<p class="fam-check-number">' + esc(t('ui.family.match_number', 'Eşleşme sayısı: {check}', { check: pending && pending.check })) + '</p>'
    + '<p class="field-hint">' + esc(t('ui.family.match_hint', 'Kod sahibine bu sayıyı söyleyin; ekrandaki sayı aynıysa onaylasın.')) + '</p>'
    + '<p class="field-hint">' + esc(t('ui.family.request_date', 'İstek: {date} · 7 gün içinde onaylanmazsa silinir.', {
      date: dateText(pending && pending.requested_at),
    })) + '</p><button type="button" class="btn" data-family-action="cancel">'
    + esc(t('ui.family.cancel_request', 'İsteği geri al')) + '</button></div>';
}

function requestMarkup(requests) {
  if (!requests.length) return '';
  const first = requests[0];
  const more = requests.length > 1
    ? '<p class="field-hint">' + esc(t('ui.family.more_requests', '{count} istek daha bekliyor', { count: requests.length - 1 })) + '</p>' : '';
  return '<section class="fam-request"><h3>' + esc(t('ui.family.request_title', 'Katılma isteği')) + '</h3>'
    + '<p>' + esc(first.display_name) + ' · ' + esc(t('ui.family.match_number_inline', 'eşleşme sayısı {check}', { check: first.check }))
    + ' · ' + dateText(first.requested_at) + '</p><p class="field-hint">'
    + esc(t('ui.family.request_hint', 'İsteyen kişiye eşleşme sayısını sorun; aynıysa onaylayın.')) + '</p><div class="btn-row">'
    + '<button type="button" class="btn btn-primary" data-family-action="approve" data-request-id="' + esc(first.id) + '">'
    + esc(t('ui.family.approve', 'Onayla')) + '</button><button type="button" class="btn" data-family-action="reject" data-request-id="'
    + esc(first.id) + '">' + esc(t('ui.family.reject', 'Reddet')) + '</button></div>' + more + '</section>';
}

function codeMarkup(family, hasRequests) {
  const code = family.code;
  if (!code) return '<p class="field-hint fam-full">' + esc(t('ui.family.family_full', 'Aile dolu (6/6). Yeni üye için birini çıkarın.')) + '</p>';
  if (code.expired) {
    const renewClass = hasRequests ? 'btn' : 'btn btn-primary';
    return '<section class="fam-code-panel"><p>' + esc(t('ui.family.code_expired', 'Kodun süresi doldu.')) + '</p>'
      + '<button type="button" class="' + renewClass + '" data-family-action="renew">'
      + esc(t('ui.family.renew_code', 'Kodu yenile')) + '</button></section>';
  }
  const copyClass = hasRequests ? 'btn' : 'btn btn-primary';
  return '<section class="fam-code-panel"><p class="fam-code"><span aria-hidden="true">' + esc(code.display)
    + '</span><span class="sr-only">' + esc(Array.from(code.code || '').join(' ')) + '</span></p>'
    + '<p class="field-hint">' + esc(t('ui.family.expires', 'Son geçerlilik: {date}', { date: dateText(code.expires_at) })) + '</p>'
    + '<div class="btn-row"><button type="button" class="' + copyClass + '" data-family-action="copy">'
    + esc(t('ui.family.copy_code', 'Kodu kopyala')) + '</button><button type="button" class="btn btn-quiet" data-family-action="renew">'
    + esc(t('ui.family.renew_code', 'Kodu yenile')) + '</button></div><p class="field-hint">'
    + esc(t('ui.family.renew_hint', 'Yenileyince eski kod geçersiz olur; bekleyen istekler kalır.')) + '</p></section>';
}

function memberMarkup(member, isOwner, newMemberIds) {
  const role = member.role === 'owner'
    ? '<span class="tag">' + esc(t('ui.family.code_owner', 'kod sahibi')) + '</span>' : '';
  const isMe = member.is_me ? ' <span class="field-hint">(' + esc(t('ui.family.you', 'siz')) + ')</span>' : '';
  const follows = member.shares && member.shares.follows || [];
  const stops = member.shares && member.shares.stops || [];
  const shared = follows.length || stops.length
    ? '<p class="field-hint">' + (follows.length ? esc(t('ui.family.follows_label', 'Takip:')) + ' <span lang="tr">'
      + follows.map((item) => esc(item.label)).join(', ') + '</span>' : '')
      + (follows.length && stops.length ? '<br>' : '')
      + (stops.length ? esc(t('ui.family.stops_label', 'Duraklar:')) + ' <span lang="tr">'
        + stops.map((item) => esc(item.line) + ' · ' + esc(item.stop)).join(', ') + '</span>' : '') + '</p>'
    : '<p class="field-hint">' + esc(t('ui.family.shares_empty', 'Henüz bir şey paylaşmadı.')) + '</p>';
  const remove = isOwner && !member.is_me && member.role !== 'owner'
    ? '<details class="fam-remove"><summary>' + esc(t('ui.family.remove_summary', 'Çıkar')) + '</summary><p class="field-hint">'
      + esc(t('ui.family.remove_warning', '{name} aileden çıkarılır; paylaşımları silinir.', { name: member.display_name }))
      + '</p><button type="button" class="btn" data-family-action="remove" data-member-id="' + esc(member.id) + '">'
      + esc(t('ui.family.remove_member', 'Aileden çıkar')) + '</button></details>' : '';
  const fresh = newMemberIds.includes(member.id) ? ' fam-member-new' : '';
  return '<li class="fam-member' + fresh + '"><div class="fam-member-heading"><span>'
    + esc(member.display_name) + isMe + '</span> ' + role + '</div>' + shared + remove + '</li>';
}

function membersMarkup(family, isOwner, newMemberIds) {
  const members = family.members || [];
  const title = esc(t('ui.family.members_title', 'Üyeler ({count}/6)', { count: members.length }));
  if (isOwner && members.length === 1) {
    return '<section class="fam-members"><h3>' + title + '</h3><p class="field-hint">'
      + esc(t('ui.family.owner_alone', 'Henüz üye yok. Kodu paylaşın; gelen istekler burada görünür.')) + '</p></section>';
  }
  return '<section class="fam-members"><h3>' + title + '</h3><ul class="fam-member-list">'
    + members.map((member) => memberMarkup(member, isOwner, newMemberIds)).join('') + '</ul></section>';
}

function sharesMarkup(view, deviceStops) {
  const mine = view.mine || { follows: [], stops: [] };
  const follows = mine.follows || [];
  const selected = new Set((mine.stops || []).map((item) => String(item.line).toUpperCase() + '|' + item.stop));
  const stopMap = new Map();
  (deviceStops || []).forEach((item) => stopMap.set(String(item.line).toUpperCase() + '|' + item.stop, item));
  (mine.stops || []).forEach((item) => stopMap.set(String(item.line).toUpperCase() + '|' + item.stop, item));
  const stops = Array.from(stopMap.values());
  const followRows = follows.length ? follows.map((item) => '<label class="check"><input type="checkbox" name="follow_ids" value="'
    + esc(item.id) + '"' + (item.shared ? ' checked' : '') + '><span lang="tr">' + esc(item.label) + '</span></label>').join('')
    : '<p class="field-hint">' + esc(t('ui.family.follows_empty', 'Takip ettiğiniz konu yok.')) + ' <a href="#takip">'
      + esc(t('ui.family.go_follows', 'Takiplerinize gidin')) + '</a></p>';
  const stopRows = stops.length ? stops.map((item) => {
    const key = String(item.line).toUpperCase() + '|' + item.stop;
    return '<label class="check"><input type="checkbox" name="stops" data-line="' + esc(item.line)
      + '" data-stop="' + esc(item.stop) + '"' + (selected.has(key) ? ' checked' : '') + '><span lang="tr">'
      + esc(item.line) + ' · ' + esc(item.stop) + '</span></label>';
  }).join('') : '<p class="field-hint">' + esc(t('ui.family.stops_empty', 'Bu cihazda kayıtlı durak yok.')) + '</p>';
  return '<details class="fam-shares"><summary>' + esc(t('ui.family.shares_summary', 'Ailemle paylaştıklarım')) + '</summary>'
    + '<form class="fam-form fam-share-form" data-family-shares><fieldset><legend>'
    + esc(t('ui.family.follows_legend', 'Takip ettiğim konular')) + '</legend>' + followRows + '</fieldset><fieldset><legend>'
    + esc(t('ui.family.stops_legend', 'Duraklarım')) + '</legend>' + stopRows + '<p class="field-hint fam-stop-warning">'
    + esc(t('ui.family.stop_privacy_hint', 'Durak adı sık gittiğiniz yeri gösterebilir; yalnız paylaşmak istediklerinizi seçin.'))
    + '</p></fieldset><button type="submit" class="btn">' + esc(t('ui.family.save_shares', 'Paylaşımı kaydet'))
    + '</button></form></details>';
}

function exitMarkup(isOwner) {
  const heading = isOwner ? esc(t('ui.family.dissolve_summary', 'Aileyi dağıt')) : esc(t('ui.family.leave_summary', 'Aileden ayrıl'));
  const warning = isOwner
    ? esc(t('ui.family.dissolve_warning', 'Tüm üyeler çıkarılır, paylaşımlar silinir, kodunuz geçersiz olur.'))
    : esc(t('ui.family.leave_warning', 'Paylaşımlarınız silinir; yeniden katılmak için yeni istek gerekir.'));
  const action = isOwner ? 'leave' : 'leave';
  const button = isOwner ? esc(t('ui.family.dissolve', 'Aileyi dağıt')) : esc(t('ui.family.leave', 'Ayrıl'));
  return '<details class="fam-exit"><summary>' + heading + '</summary><p class="field-hint">' + warning + '</p>'
    + '<button type="button" class="btn" data-family-action="' + action + '">' + button + '</button></details>';
}

function familyView(view, deviceStops = [], newMemberIds = []) {
  const family = view.family || { count: 0, limit: 6, members: [] };
  const isOwner = view.state === 'owner';
  const requests = isOwner ? (family.requests || []) : [];
  const noCodePanel = isOwner && family.count >= family.limit;
  return bandMarkup() + (isOwner ? requestMarkup(requests) : '')
    + (isOwner ? (noCodePanel ? '<p class="field-hint fam-full">'
      + esc(t('ui.family.family_full', 'Aile dolu (6/6). Yeni üye için birini çıkarın.')) + '</p>' : codeMarkup(family, requests.length > 0)) : '')
    + membersMarkup(family, isOwner, newMemberIds) + sharesMarkup(view, deviceStops) + exitMarkup(isOwner);
}

function familyMarkup(view, deviceStops = [], newMemberIds = []) {
  if (!view || view.state === 'none') return startView(view && view.consent);
  if (view.state === 'pending') return pendingView(view.pending || {});
  return familyView(view, deviceStops, newMemberIds);
}

export {
  CODE_ALPHABET, FAMILY_BAND, normalizeCode, formatCode, startView, pendingView, familyView, familyMarkup,
};
