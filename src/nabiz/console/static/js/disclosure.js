import { esc } from './format.js';
import { icon } from './icons.js';

const AI_NOTICE = 'Ben İstanbul şehir bilgi asistanıyım ve yapay zekâ kullanıyorum. Resmî karar veren bir görevli değilim.';
const PRIVACY_NOTICE = 'Profiliniz telefonunuzda ya da bilgisayarınızda kalır, sunucuya gitmez. Ses kaydı tutulmaz. Sunucuda kişisel veri saklanmaz; sorunuz loglanmaz. Yurt dışındaki modele kişisel veriniz gönderilmez; yalnız yazdığınız soru gider.';
const PII_WARNING = 'Soruya TC kimlik, kart numarası, sağlık belgesi gibi kişisel bilgileri yazmayın.';

function privacyBandMarkup() {
  return `<div class="chat-band privacy-band" id="privacy-band">${icon('shield-lock')}<p><b>Gizlilik.</b> `
    + `${esc(PRIVACY_NOTICE)} ${esc(PII_WARNING)} <a href="/kvkk.html">Kişisel veriler ve gizlilik: tam metin</a></p></div>`;
}

function aiNoticeMarkup() {
  return `<p class="chat-ai-notice">${esc(AI_NOTICE)}</p>`;
}

function mountDisclosure({ section, log }) {
  if (typeof document === 'undefined' || !section || !log) return;
  if (!section.querySelector('#privacy-band')) {
    const chatBand = section.querySelector('.chat-band');
    if (chatBand) chatBand.insertAdjacentHTML('afterend', privacyBandMarkup());
    else log.insertAdjacentHTML('beforebegin', privacyBandMarkup());
  }

  const discloseFirst = () => {
    const message = log.querySelector('li.chat-msg.is-assistant');
    if (!message) return false;
    let notice = message.querySelector('.chat-ai-notice');
    if (!notice) {
      notice = document.createElement('p');
      notice.className = 'chat-ai-notice';
      const speaker = message.querySelector('.chat-who');
      if (speaker) speaker.insertAdjacentElement('afterend', notice);
      else message.insertAdjacentElement('afterbegin', notice);
    }
    notice.textContent = AI_NOTICE;
    notice.hidden = false;
    return true;
  };

  if (discloseFirst()) return;
  const observer = new MutationObserver(() => {
    if (discloseFirst()) observer.disconnect();
  });
  observer.observe(log, { childList: true, subtree: true });
}

if (typeof document !== 'undefined') {
  const section = document.querySelector('#asistan');
  const log = document.querySelector('#chat-log');
  if (section && log) mountDisclosure({ section, log });
}

export { AI_NOTICE, PRIVACY_NOTICE, PII_WARNING, privacyBandMarkup, aiNoticeMarkup, mountDisclosure };
