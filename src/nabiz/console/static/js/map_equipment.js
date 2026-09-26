/* Pure helpers for recorded escalator and moving walkway rows. */
export const EQUIPMENT_LAYERS = ['escalators', 'walkways'];
export const LAYER_TYPE = { escalators: 'escalator', walkways: 'moving_walkway' };
export const TYPE_TR = { escalator: 'yürüyen merdiven', moving_walkway: 'yürüyen bant' };

export function layersTemplate() {
  return '<section id="harita-katmanlari" aria-labelledby="map-layers-title">'
    + '<div class="section-head"><h2 id="map-layers-title" tabindex="-1">Raylı sistem istasyonları ve ekipman kayıtları</h2></div>'
    + '<p class="map-layers-intro">Metro, tramvay ve füniküler istasyonları. Ekipman bilgisi Metro İstanbul kayıtlarından gelir. Kayıtta olmayan ekipmanın kullanılabilir olduğu doğrulanmış değildir.</p>'
    + '<div class="map-layers-actions"><button type="button" class="btn btn-primary" id="map-layers-show"><span>Haritada göster</span></button>'
    + '<fieldset class="map-layers-toggles"><legend>Katmanlar</legend>'
    + '<label><input type="checkbox" id="map-layers-stations-toggle" checked> İstasyonlar</label>'
    + '<label><input type="checkbox" id="map-layers-lifts-toggle" checked> Asansör kayıtları</label>'
    + '<label><input type="checkbox" id="map-layers-escalators-toggle" checked> Yürüyen merdiven</label>'
    + '<label><input type="checkbox" id="map-layers-walkways-toggle" checked> Yürüyen bant</label></fieldset></div>'
    + '<p class="status-line" id="map-layers-status" role="status"></p><div id="map-layers-lists" hidden>'
    + '<h3 id="map-layers-lifts-title">Asansör kayıtları</h3><ol id="map-layers-lifts" class="map-layers-list" aria-labelledby="map-layers-lifts-title"></ol>'
    + '<h3 id="map-layers-equipment-title">Yürüyen merdiven ve bant kayıtları</h3>'
    + '<ol id="map-layers-equipment" class="map-layers-list" aria-labelledby="map-layers-equipment-title"></ol>'
    + '<h4 id="map-layers-equipment-off-title" class="map-layers-subhead">İBB kaydında \'Çalıştırılmıyor\' olanlar</h4>'
    + '<ol id="map-layers-equipment-off" class="map-layers-list" aria-labelledby="map-layers-equipment-off-title"></ol>'
    + '<h3 id="map-layers-stations-title">İstasyonlar</h3><ol id="map-layers-stations" class="map-layers-list" aria-labelledby="map-layers-stations-title"></ol>'
    + '<details id="map-layers-more"><summary></summary><ol id="map-layers-stations-more" class="map-layers-list" start="21"></ol></details>'
    + '<p class="map-layers-foot"></p></div></section>';
}

export function unreadEquipment() {
  return {
    count: 0,
    counts: { escalator: 0, moving_walkway: 0 },
    equipment_record: 'unread',
    stale: false,
    features: [],
    note: 'Yürüyen merdiven ve bant kaydı okunamadı; durumları doğrulanamadı.',
    provenance: { source: 'metro_equipment', url: null, observed_at: null, age_s: null, mode: 'unknown' },
    uncertainty: [],
    date_label: null,
    disclaimer: null,
  };
}

export function equipmentFeatures(collection, layers) {
  const selected = new Set(layers || []);
  const types = EQUIPMENT_LAYERS.filter((layer) => selected.has(layer)).map((layer) => LAYER_TYPE[layer]);
  return collection && Array.isArray(collection.features)
    ? collection.features.filter((feature) => types.includes((feature.properties || {}).equipment_type)) : [];
}

export function equipmentRowText(feature) {
  const p = feature && feature.properties ? feature.properties : {};
  return (p.text || '') + (p.placed === false ? ' · Haritada yeri bulunamadı' : '');
}

export function splitNotOperated(features) {
  return features.reduce((groups, feature) => {
    groups[feature.properties && feature.properties.not_operated ? 'notOperated' : 'active'].push(feature);
    return groups;
  }, { active: [], notOperated: [] });
}

export function stationTypes(collection, layers) {
  const result = new Map();
  equipmentFeatures(collection, layers).forEach((feature) => {
    const p = feature.properties || {};
    if (p.placed !== true || !p.station || !TYPE_TR[p.equipment_type]) return;
    if (!result.has(p.station)) result.set(p.station, new Set());
    result.get(p.station).add(p.equipment_type);
  });
  return result;
}
