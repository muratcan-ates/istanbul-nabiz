import { esc } from './format.js';
import { icon } from './icons.js';

const AI_NOTICE = 'Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim.';
const PRIVACY_NOTICE = 'Profiliniz telefonunuzda ya da bilgisayarınızda kalır, sunucuya gitmez. Ses kaydı tutulmaz. Hesapsız kullanımda sunucuda kişisel veri saklanmaz; operatöre ilettiğiniz talepler ve fotoğraflı bildirimler maskelenerek 30 gün tutulur. Sorunuz loglanmaz. Yurt dışındaki modele kişisel veriniz gönderilmez; yalnız yazdığınız soru gider.';
const PII_WARNING = 'Soruya TC kimlik, kart numarası, sağlık belgesi gibi kişisel bilgileri yazmayın.';

function privacyBandMarkup() {
  return `<div class="chat-band privacy-band" id="privacy-band">${icon('shield-lock')}<p><b>Gizlilik.</b> `
    + `${esc(PRIVACY_NOTICE)} ${esc(PII_WARNING)} <a href="/kvkk.html">Kişisel veriler ve gizlilik: tam metin</a></p></div>`;
}

/* The AI notice is shown once per page session, as the band chat.js puts at the top of the log when the
 * first answer starts. The first answer does not repeat it: the notice reads once on screen. */
function aiNoticeMarkup() {
  return `<div class="chat-band" role="note"><p>${esc(AI_NOTICE)}</p></div>`;
}

function mountDisclosure({ section, log }) {
  if (typeof document === 'undefined' || !section || !log) return;
  if (section.querySelector('#privacy-band')) return;
  const chatBand = section.querySelector('.chat-band');
  if (chatBand) chatBand.insertAdjacentHTML('afterend', privacyBandMarkup());
  else log.insertAdjacentHTML('beforebegin', privacyBandMarkup());
}

if (typeof document !== 'undefined') {
  const section = document.querySelector('#asistan');
  const log = document.querySelector('#chat-log');
  if (section && log) mountDisclosure({ section, log });
}

export { AI_NOTICE, PRIVACY_NOTICE, PII_WARNING, privacyBandMarkup, aiNoticeMarkup, mountDisclosure };
