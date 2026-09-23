/* İSPARK lots: free spaces against capacity, how full, and the tariff as a table. Pure. */

import { esc, num, int, has } from '../format.js';
import { cardShell, metaList } from './shell.js';

function fillBar(pct) {
  if (pct === null || pct === undefined) return '';
  const cls = pct >= 90 ? 'bad' : pct >= 70 ? 'warn' : '';
  return `<div class="bar"><i class="${cls}" style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>`;
}

/** İSPARK ships the tariff as "0-1 Saat : 110,00;1-2 Saat : 140,00" — make it a table. */
function tariffTable(raw) {
  if (!raw) return '';
  const rows = String(raw).split(';').map((part) => part.split(':')).filter((p) => p.length >= 2);
  if (!rows.length) return `<p class="hint">${esc(raw)}</p>`;
  const body = rows.map(([label, value]) => `<tr><td>${esc(label.trim())}</td><td>${esc(value.trim())} ₺</td></tr>`).join('');
  return `<details class="tariff"><summary>Tarife (${rows.length} kademe)</summary><table><tbody>${body}</tbody></table></details>`;
}

function parkingCard(lot, prov, id) {
  const capacity = lot.capacity || 0;
  const empty = has(lot.empty) ? lot.empty : null;
  const occupied = capacity && empty !== null ? Math.max(0, capacity - empty) : null;
  const pct = capacity && occupied !== null ? Math.round((occupied / capacity) * 100) : null;
  const meta = [
    lot.park_type, lot.district, lot.work_hours,
    lot.free_minutes ? `ilk ${int(lot.free_minutes)} dk ücretsiz` : null,
    has(lot.monthly_fee) ? `aylık ${int(lot.monthly_fee)} ₺` : null,
    lot.is_open === false ? 'şu anda kapalı' : null,
  ];
  const body = `
    <div class="metric"><b>${empty === null ? '—' : int(empty)}</b><span class="unit">boş yer</span>
      ${capacity ? `<span class="metric-note">${int(capacity)} kapasite</span>` : ''}</div>
    ${fillBar(pct)}
    ${pct === null ? '' : `<div class="bar-legend"><span>%${int(pct)} dolu</span><span>${has(lot.distance_km) ? `${num(lot.distance_km)} km uzakta` : ''}</span></div>`}
    ${metaList(meta)}
    ${tariffTable(lot.tariff)}`;
  return cardShell({
    id, kind: 'park', icon: 'park', prov, body,
    title: lot.name,
    // The distance already appears under the fill bar; repeating it here read as noise.
    sub: lot.address || '',
  });
}

export { parkingCard };
