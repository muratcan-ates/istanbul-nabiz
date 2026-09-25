/* The one place both pages are configured.
 *
 * Real endpoints: API_BASE stays '' (same origin: the console app serves the pages and /api/*).
 * Mock: /mock/*.json is served from static/ and needs no server logic; append ?mock=1 to the page
 * URL, or flip MOCK_DEFAULT. ?mock=0 forces the real endpoints whatever the default. */

export const API_BASE = ''; // the single line to change for another host, e.g. 'http://127.0.0.1:8090'
export const MOCK_DEFAULT = false;

/** Cards shown before the visitor saves any place (js/profile.js adds theirs). */
export const DEFAULT_STATIONS = ['Kartal', 'Kadıköy'];
export const DEFAULT_LINES = ['M4', '500T'];
export const DEFAULT_ARRIVAL = { line: '500T', stop: 'Şifa Sondurak' };

/** Console: evidence older than this is flagged beside the freshness figure. A design parameter,
 * not a measured threshold (NABIZ-TAM-PLAN §4b says every threshold there is an assumption). */
export const FRESHNESS_WARN_S = 900;
/** Turns of the conversation sent back with each question. */
export const HISTORY_TURNS = 6;
/** Cards and the arrival refresh on this cadence while the tab is visible. */
export const REFRESH_MS = 60_000;

export function isMock(search) {
  const q = new URLSearchParams(search || '');
  if (q.has('mock')) return q.get('mock') !== '0';
  return MOCK_DEFAULT;
}
