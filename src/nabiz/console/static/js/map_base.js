/* An offline sample base map: rough sea shapes and district names drawn as Leaflet vectors, so no
 * map picture is ever fetched from another server. The shapes are approximate; the markers the pages
 * draw on top keep their real coordinates. tests/test_map_base.py keeps every station on land.
 * Coordinates are [lat, lon]. Colours come from css/map_base.css tokens, never from here. */

export const BASE_NOTE = 'Örnek harita altlığı; kıyılar yaklaşık';
const STYLE = '/css/map_base.css';
const SEA_PANE = 'nabizBaseSea';
const LABEL_PANE = 'nabizBaseLabels';
const LABEL_MIN_ZOOM = 11;

/* Black Sea, the Bosphorus and the Sea of Marmara as one ring, walked from the north-west: the
 * Thracian Black Sea coast, the European bank of the Bosphorus southwards, the historic peninsula and
 * the Marmara north coast westwards, the south coast eastwards, the Anatolian coast northwards to
 * Üsküdar and up the Asian bank of the Bosphorus to the Anatolian Black Sea coast. */
const SEA_RING = [
  [41.9, 27.8], [41.63, 28.0], [41.45, 28.35], [41.35, 28.68], [41.28, 28.9], [41.255, 29.02], [41.25, 29.075],
  [41.246, 29.1], [41.235, 29.11],
  // Bosphorus, European bank
  [41.21, 29.085], [41.185, 29.073], [41.168, 29.061], [41.155, 29.052], [41.14, 29.058], [41.128, 29.069],
  [41.122, 29.068], [41.113, 29.06], [41.105, 29.057], [41.095, 29.056], [41.085, 29.057], [41.08, 29.056],
  [41.077, 29.048], [41.068, 29.046], [41.058, 29.036], [41.049, 29.031], [41.047, 29.029], [41.044, 29.018],
  [41.041, 29.0105], [41.036, 28.999], [41.031, 28.994], [41.026, 28.987], [41.0215, 28.983],
  // Golden Horn mouth, Sarayburnu, Marmara north coast
  [41.018, 28.983], [41.0165, 28.986], [41.012, 28.985], [41.0075, 28.983], [41.0015, 28.978], [40.999, 28.97],
  [40.998, 28.961], [40.997, 28.95], [40.99, 28.935], [40.985, 28.915], [40.981, 28.895], [40.976, 28.878],
  [40.97, 28.866], [40.966, 28.855], [40.957, 28.83], [40.955, 28.815], [40.963, 28.79], [40.97, 28.75],
  [40.966, 28.72], [40.962, 28.68], [40.962, 28.64], [40.962, 28.61], [40.967, 28.595], [40.975, 28.585], [40.985, 28.565],
  [40.99, 28.54], [40.993, 28.51], [41.0, 28.49], [41.02, 28.45], [41.013, 28.4], [41.06, 28.3], [41.07, 28.2],
  [40.97, 27.55], [40.85, 27.3],
  // Marmara south coast
  [40.45, 27.2], [40.4, 27.8], [40.36, 28.0], [40.38, 28.5], [40.37, 28.85], [40.42, 29.05], [40.55, 29.0],
  [40.62, 29.1], [40.655, 29.27], [40.7, 29.45], [40.72, 29.6], [40.76, 29.6], [40.77, 29.42], [40.805, 29.35],
  // Anatolian coast, Tuzla to Üsküdar
  [40.808, 29.32], [40.815, 29.295], [40.838, 29.27], [40.858, 29.25], [40.872, 29.232], [40.88, 29.2],
  [40.886, 29.18], [40.893, 29.16], [40.897, 29.145], [40.91, 29.13], [40.918, 29.12], [40.928, 29.108],
  [40.945, 29.093], [40.955, 29.075], [40.963, 29.055], [40.965, 29.04], [40.972, 29.03], [40.978, 29.024],
  [40.985, 29.019], [40.992, 29.018], [40.998, 29.015], [41.005, 29.008], [41.012, 29.004], [41.019, 29.0065],
  [41.025, 29.0078], [41.028, 29.0125],
  // Bosphorus, Asian bank
  [41.033, 29.021], [41.037, 29.029], [41.042, 29.038], [41.047, 29.045], [41.052, 29.049], [41.058, 29.05],
  [41.062, 29.052], [41.064, 29.056], [41.075, 29.062], [41.083, 29.065], [41.1, 29.064], [41.107, 29.075],
  [41.117, 29.086], [41.132, 29.089], [41.14, 29.083], [41.148, 29.084], [41.155, 29.086], [41.175, 29.086],
  [41.195, 29.1], [41.215, 29.14], [41.225, 29.18],
  // Anatolian Black Sea coast
  [41.215, 29.35], [41.21, 29.42], [41.195, 29.5], [41.18, 29.62], [41.14, 30.0], [41.2, 30.4], [41.9, 30.4],
];

/* The Princes' Islands, cut out of the sea ring. */
const ISLANDS = [
  [[40.878, 29.118], [40.876, 29.14], [40.862, 29.142], [40.845, 29.13], [40.84, 29.115], [40.855, 29.103],
    [40.87, 29.11]],
  [[40.885, 29.09], [40.88, 29.105], [40.87, 29.1], [40.872, 29.085]],
  [[40.886, 29.066], [40.88, 29.074], [40.874, 29.066], [40.88, 29.058]],
  [[40.915, 29.052], [40.91, 29.058], [40.905, 29.052], [40.91, 29.046]],
];

/* The Golden Horn in two parts, so the metro bridge (Haliç station) stays dry between them. */
const GOLDEN_HORN = [
  [[41.0215, 28.984], [41.0214, 28.976], [41.0225, 28.97], [41.024, 28.968],
    [41.0215, 28.968], [41.0195, 28.972], [41.0185, 28.976], [41.018, 28.984]],
  [[41.0228, 28.9645], [41.0265, 28.96], [41.031, 28.955], [41.035, 28.949], [41.04, 28.9455], [41.045, 28.942],
    [41.05, 28.938], [41.0525, 28.9395], [41.0525, 28.942], [41.047, 28.946], [41.042, 28.95], [41.037, 28.9545],
    [41.033, 28.96], [41.0285, 28.964], [41.025, 28.9645]],
];

export const SEA = [[SEA_RING, ...ISLANDS], ...GOLDEN_HORN.map((ring) => [ring])];

/* Scenery, not information: hidden from screen readers and never added to a page's point list. */
export const DISTRICTS = [
  ['Fatih', 41.017, 28.945], ['Beyoğlu', 41.036, 28.977], ['Beşiktaş', 41.058, 29.012], ['Şişli', 41.065, 28.985],
  ['Sarıyer', 41.15, 29.02], ['Bakırköy', 40.99, 28.86], ['Başakşehir', 41.095, 28.8], ['Üsküdar', 41.025, 29.05],
  ['Kadıköy', 40.985, 29.06], ['Ümraniye', 41.02, 29.12], ['Kartal', 40.905, 29.2], ['Pendik', 40.89, 29.28],
];

function ensureStyle() {
  try {
    if (document.querySelector(`link[href="${STYLE}"]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = STYLE;
    document.head.append(link);
  } catch {
    // Without the sheet the sea stays transparent over the page's map wash; markers still draw.
  }
}

function quietPane(map, name, zIndex) {
  const pane = map.getPane(name) || map.createPane(name);
  pane.style.zIndex = String(zIndex);
  pane.style.pointerEvents = 'none';
  pane.setAttribute('aria-hidden', 'true');
  return pane;
}

function escapeText(text) {
  return String(text).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);
}

function districtLabel(L, [name, lat, lon]) {
  const text = document.createElement('span');
  text.textContent = name;
  return L.marker([lat, lon], {
    icon: L.divIcon({ className: 'map-base-label', html: text, iconSize: null }),
    pane: LABEL_PANE,
    interactive: false,
    keyboard: false,
  });
}

/** Build the sample base for a Leaflet map; the caller adds the returned group to the map. */
export function mockBase(L, map, { attribution = BASE_NOTE } = {}) {
  ensureStyle();
  map.getContainer().classList.add('map-base');
  quietPane(map, SEA_PANE, 150);
  const labels = quietPane(map, LABEL_PANE, 350);
  const sea = SEA.map((rings) => L.polygon(rings, {
    pane: SEA_PANE,
    className: 'map-base-sea',
    interactive: false,
    stroke: false,
    fillColor: 'transparent',
    fillOpacity: 1,
  }));
  const names = DISTRICTS.map((district) => districtLabel(L, district));
  const showLabels = () => {
    const zoom = map.getZoom();
    labels.hidden = Number.isFinite(zoom) && zoom < LABEL_MIN_ZOOM;
  };
  map.on('zoomend', showLabels);
  showLabels();
  return L.layerGroup([...sea, ...names], { attribution: escapeText(attribution) });
}
