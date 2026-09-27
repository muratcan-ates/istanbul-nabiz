import { dateTime, esc, shortAge } from './format.js';
import { currentLang, t } from './i18n_text.js';
import { ageText, modeOf, sourceLabel } from './provenance.js';

const actionsByLog = new WeakMap();
const INSTITUTIONS = {
  IBB: 'İBB', IBB_OPEN_DATA: 'İBB Açık Veri Portalı', IETT: 'İETT', IGDAS: 'İGDAŞ',
  ISKI: 'İSKİ', ISPARK: 'İSPARK', METRO_ISTANBUL: 'Metro İstanbul', SEHIR_HATLARI: 'Şehir Hatları',
};

function foldedQuestion(value) {
  return String(value ?? '').normalize('NFKC').toLocaleLowerCase('tr').replace(/\s+/g, ' ').trim();
}

function nextChips(payload, askedText, lang = 'tr', limit = 2) {
  const categories = Array.isArray(payload && payload.categories) ? payload.categories : [];
  const language = lang === 'en' ? 'en' : 'tr';
  const textOf = (chip) => language === 'en' ? chip.text_en : chip.text_tr;
  const asked = foldedQuestion(askedText);
  const category = categories.find((item) => Array.isArray(item.chips)
    && item.chips.some((chip) => foldedQuestion(textOf(chip)) === asked)) || categories[0];
  const count = Number.isInteger(limit) ? Math.max(0, limit) : 2;
  if (!category || !Array.isArray(category.chips) || !count) return [];
  return category.chips
    .filter((chip) => typeof chip.id === 'string' && typeof textOf(chip) === 'string'
      && foldedQuestion(textOf(chip)) !== asked)
    .slice(0, count)
    .map((chip) => ({ id: chip.id, text: textOf(chip) }));
}

function freshnessText(citation) {
  if (citation.source === 'local:knowledge') {
    const date = citation.source_updated_at || citation.fetched_at;
    const prefix = t('dynp.recorded', 'Kayıtlı veri ·').trim();
    return date ? `${prefix} ${dateTime(date)}` : t('dyn.kind_page', 'Resmî sayfadan alıntı');
  }
  const mode = citation.mode === 'old' ? 'old' : modeOf(citation);
  if (mode === 'live') return `${t('dynp.live', 'Canlı veri ·').trim()} ${shortAge(citation.age_s)}`;
  if (mode === 'old') return `${t('dynp.measured', 'Ölçüm ·').trim()} ${ageText(citation)}`;
  if (mode === 'recorded') return `${t('dynp.recorded', 'Kayıtlı veri ·').trim()} ${ageText(citation)}`;
  if (mode === 'schedule') return t('dyn.kind_schedule', 'Tarifeye göre');
  return t('dyn.kind_unknown', 'Veri yaşı bilinmiyor');
}

function sourceName(citation) {
  if (citation.source === 'local:knowledge') {
    return INSTITUTIONS[citation.institution] || citation.title || citation.institution || sourceLabel(citation.source);
  }
  return sourceLabel(citation.source || citation.institution);
}

function copyText(finalData) {
  const data = finalData && typeof finalData === 'object' ? finalData : {};
  const first = Array.isArray(data.citations) ? data.citations.find(Boolean) : null;
  const answer = data.mode === 'quote_only' && first && typeof first.quote === 'string'
    ? first.quote : data.answer_text ?? data.answer ?? '';
  if (!first) return String(answer).trim();
  const label = currentLang() === 'en' ? 'Source' : 'Kaynak';
  return `${String(answer).trim()}\n${label}: ${sourceName(first)} · ${freshnessText(first)}`;
}

function mountAnswerActions(log, { input, form, status } = {}) {
  if (!log || !input || !form) return { remember() {}, showNextChips() {} };
  const existing = actionsByLog.get(log);
  if (existing) return existing;
  const finalByShell = new WeakMap();
  let quickRequested = false;

  log.addEventListener('click', async (event) => {
    const target = event.target;
    const copyButton = target && target.closest && target.closest('[data-ac-copy]');
    if (copyButton) {
      const shell = copyButton.closest('.chat-msg');
      const finalData = shell && finalByShell.get(shell);
      if (!finalData) return;
      copyButton.setAttribute('aria-busy', 'true');
      try {
        const clipboard = globalThis.navigator && globalThis.navigator.clipboard;
        if (!clipboard || typeof clipboard.writeText !== 'function') throw new Error('clipboard unavailable');
        await clipboard.writeText(copyText(finalData));
        if (status) status.textContent = t('dyn.copied', 'Kopyalandı.');
      } catch {
        if (status) status.textContent = t('dyn.copy_failed', 'Kopyalanamadı; metni seçip kopyalayabilirsiniz.');
      } finally {
        copyButton.removeAttribute('aria-busy');
      }
      return;
    }
    const chip = target && target.closest && target.closest('button[data-next-chip]');
    if (!chip || !form || !input) return;
    input.value = chip.dataset.nextChip;
    input.focus();
    form.requestSubmit();
  });

  const actions = {
    remember(shell, finalData) {
      if (shell && finalData && typeof finalData === 'object') finalByShell.set(shell, finalData);
    },
    async showNextChips(host, finalData, askedText, lang = document.documentElement.lang) {
      if (quickRequested || !host || !finalData || !['answer', 'quote_only'].includes(finalData.mode)) return;
      quickRequested = true;
      try {
        const { get } = await import('./api.js');
        const chips = nextChips(await get('/api/quick'), askedText, lang, 2);
        if (!chips.length || !host.isConnected) return;
        const title = t('dyn.next_title', 'Şunu da sorabilirsiniz');
        const group = document.createElement('div');
        group.className = 'ac-next';
        group.setAttribute('data-ac-next', '');
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', title);
        group.innerHTML = `<p class="eyebrow">${esc(title)}</p><div class="chips">${chips.map((chip) => (
          `<button type="button" class="chip" data-next-chip="${esc(chip.text)}">${esc(chip.text)}</button>`
        )).join('')}</div>`;
        host.append(group);
      } catch {
        // Suggestions are optional; a failed lookup does not change the answer.
      }
    },
  };
  actionsByLog.set(log, actions);
  return actions;
}

export { mountAnswerActions, copyText, nextChips };
