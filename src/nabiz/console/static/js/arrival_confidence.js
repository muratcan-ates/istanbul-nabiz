import { esc } from './format.js';
import { icon } from './icons.js';

export const MEASURED = Object.freeze({ maeMinutes: 12.94, samples: 1351, from: '2026-09-08', to: '2026-09-22', lines: ['15F', '34', '500T'], source: 'eval/results/eta.md' });

const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];

function trDecimal(value) {
  return String(value).replace('.', ',');
}

function trInt(value) {
  return String(Math.trunc(Number(value))).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function rangeTr(from, to) {
  const fromDay = Number(from.slice(8, 10));
  const toDay = Number(to.slice(8, 10));
  const fromMonth = Number(from.slice(5, 7)) - 1;
  const toMonth = Number(to.slice(5, 7)) - 1;
  const fromYear = from.slice(0, 4);
  const toYear = to.slice(0, 4);
  if (fromMonth === toMonth && fromYear === toYear) return `${fromDay}-${toDay} ${MONTHS[fromMonth]}`;
  const year = fromYear === toYear ? '' : ` ${toYear}`;
  return `${fromDay} ${MONTHS[fromMonth]}-${toDay} ${MONTHS[toMonth]}${year}`;
}

function confidenceFor(display) {
  if (typeof display !== 'string') return null;
  if (/^\d+ dk$/.test(display)) return 'measured';
  if (display === 'tarifeye göre') return 'schedule';
  if (display === 'doğrulanamadı') return 'unverified';
  return null;
}

function whyMarkup(kind, measured = MEASURED) {
  if (!kind) return '';
  if (kind === 'schedule') {
    const sentence = 'Neden sayı yok: tarife saati, taze canlı konum yok. Tarife hattın ilk durağından kalkışı söyler, bu durağa varışı değil.';
    return `<div class="arrival-why" data-why="schedule">${icon('clock-question')}<span class="arrival-why-text">${esc(sentence)}</span></div>`;
  }
  if (kind === 'unverified') {
    const sentence = 'Neden sayı yok: bu durağa yaklaşan otobüsün konumu bulunamadı ya da İETT kaynağına ulaşılamadı.';
    return `<div class="arrival-why" data-why="unverified">${icon('clock-question')}<span class="arrival-why-text">${esc(sentence)}</span></div>`;
  }
  if (kind !== 'measured') return '';
  const dateRange = rangeTr(measured.from, measured.to);
  const sampleCount = trInt(measured.samples);
  const lineNames = `${measured.lines.slice(0, -1).join(', ')} ve ${measured.lines.at(-1)}`;
  const sentence = `Neden emin değilim: ${dateRange}'de ${sampleCount} tahmini ölçtük; tahmin ortalama ${Math.round(measured.maeMinutes)} dakika kadar şaştı.`;
  return `<div class="arrival-why" data-why="measured" data-mae="${measured.maeMinutes}" data-n="${measured.samples}" data-from="${esc(measured.from)}" data-to="${esc(measured.to)}" data-source="${esc(measured.source)}">`
    + `${icon('info-circle')}<span class="arrival-why-text">${esc(sentence)}</span>`
    + '<span class="tag is-info">ölçüldü</span>'
    + `<details class="arrival-why-more" id="arrival-why-more"><summary>Nasıl ölçüldü?</summary><span>Nabız, ${esc(lineNames)} hatlarında otobüsün durağa geldiği görülen ${sampleCount} tahmini, geliş anıyla karşılaştırdı; durakta görülemeyen otobüsler sayılmadı. Konum üç dakikada bir kaydedildiği için ölçüm de yaklaşık üç dakika payla yapılır. Tarihler UTC'ye göredir. Başka hatlarda hata farklı olabilir.</span></details></div>`;
}

function restoreMore(details, state) {
  if (!details) return;
  if (state.moreOpen) details.open = true;
  if (state.moreFocused) details.querySelector('summary')?.focus({ preventScroll: true });
}

let moreOpen = false;
let moreFocused = false;

function annotateArrival(host) {
  const card = host.querySelector('#arrival-card');
  if (!card || card.querySelector('.arrival-why')) return;
  const display = card.querySelector('.card-value')?.textContent.trim();
  const kind = confidenceFor(display);
  if (kind === null) return;
  const markup = whyMarkup(kind);
  const metric = card.querySelector('.card-metric');
  if (metric) metric.insertAdjacentHTML('afterend', markup);
  else card.querySelector('.card-foot')?.insertAdjacentHTML('beforebegin', markup);
  const details = card.querySelector('#arrival-why-more');
  if (details) restoreMore(details, { moreOpen, moreFocused });
}

function mountArrivalConfidence(root = document) {
  const doc = root.nodeType === 9 ? root : root.ownerDocument;
  if (!root.querySelector('link[href="/css/progress.css"]')) {
    const head = root.querySelector('head');
    if (head && doc) {
      const link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/css/progress.css';
      head.append(link);
    }
  }
  const host = root.querySelector('#arrival');
  if (!host) return;
  annotateArrival(host);
  host.addEventListener('toggle', (event) => {
    if (event.target.id === 'arrival-why-more') moreOpen = event.target.open;
  }, true);
  host.addEventListener('focusin', (event) => {
    if (event.target.closest?.('#arrival-why-more summary')) moreFocused = true;
  });
  host.addEventListener('focusout', (event) => {
    if (event.relatedTarget) moreFocused = Boolean(event.relatedTarget.closest?.('#arrival-why-more summary'));
    else if (host.contains(event.target)) moreFocused = false;
  });
  new MutationObserver(() => annotateArrival(host)).observe(host, { childList: true });
}

if (typeof document !== 'undefined') mountArrivalConfidence();

export { trDecimal, trInt, rangeTr, confidenceFor, whyMarkup, restoreMore, annotateArrival, mountArrivalConfidence };
