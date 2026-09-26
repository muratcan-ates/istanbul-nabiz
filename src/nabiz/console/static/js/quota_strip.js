/* "Bugün kalan: 14/20 soru · daha fazlası için hesap bağla" under the question box (DECISIONS #38).
 * It asks /api/quota on load, after each answer and when the account changes. */

import { get } from './api.js';
import { quotaParts } from './account_view.js';
import { onLang, t } from './i18n_text.js';
import { esc } from './format.js';

async function refresh(host) {
  try {
    const status = await get('/api/quota');
    const { text, cta, tier } = quotaParts(status);
    host.hidden = !text;
    host.querySelector('[data-quota-text]').textContent = text;
    host.querySelector('[data-quota-tier]').textContent = tier;
    host.querySelector('[data-quota-tier]').hidden = !tier;
    host.querySelector('[data-quota-separator]').hidden = !tier;
    host.querySelector('[data-quota-cta-separator]').hidden = !cta;
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
  // "text · tier" with an account, "text · link" without one; the tier label is the server's Turkish.
  host.innerHTML = '<span data-quota-text></span><span data-quota-separator aria-hidden="true"> · </span>'
    + '<span data-quota-tier lang="tr"></span><span data-quota-cta-separator aria-hidden="true"> · </span>'
    + `<a href="#hesap">${esc(t('ui.quota.link', 'daha fazlası için hesap bağla'))}</a>`;
  refresh(host);
  document.addEventListener('nabiz:account-changed', () => refresh(host));
  onLang(() => refresh(host));
  const log = document.getElementById('chat-log');
  if (log) {
    new MutationObserver(() => { if (log.getAttribute('aria-busy') === 'false') refresh(host); })
      .observe(log, { attributes: true, attributeFilter: ['aria-busy'] });
  }
}

mountQuotaStrip();

export { mountQuotaStrip, refresh };
