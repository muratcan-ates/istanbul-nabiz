/* "Bugün kalan: 14/20 soru · daha fazlası için hesap bağla" under the question box (DECISIONS #36).
 * It asks /api/quota on load, after each answer and when the account changes. */

import { get } from './api.js';
import { quotaParts } from './account_view.js';

async function refresh(host) {
  try {
    const status = await get('/api/quota');
    const { text, cta } = quotaParts(status);
    host.hidden = !text;
    host.querySelector('span').textContent = cta ? `${text} ·` : text;
    const link = host.querySelector('a');
    link.hidden = !cta;
    link.textContent = cta;
    host.classList.toggle('is-empty', status.questions_left <= 0);
  } catch (err) {
    host.hidden = true;
  }
}

function mountQuotaStrip() {
  const host = document.getElementById('quota-strip');
  if (!host) return;
  host.innerHTML = '<span></span> <a href="#hesap"></a>';
  refresh(host);
  document.addEventListener('nabiz:account-changed', () => refresh(host));
  const log = document.getElementById('chat-log');
  if (log) {
    new MutationObserver(() => { if (log.getAttribute('aria-busy') === 'false') refresh(host); })
      .observe(log, { attributes: true, attributeFilter: ['aria-busy'] });
  }
}

mountQuotaStrip();

export { mountQuotaStrip };
