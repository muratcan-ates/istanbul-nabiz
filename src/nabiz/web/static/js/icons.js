/* icon(name): inline glyphs are in the page, the rest in /icons.svg (build_icon_sprite.py). Pure. */

const INLINE = new Set(('search arrow-right parking bus train wind traffic-lights device-desktop sun moon info-circle '
  + 'refresh clock history clock-exclamation clock-question bus-stop route external-link').split(' '));

function icon(name, cls) {
  const href = `${INLINE.has(name) ? '' : '/icons.svg'}#i-${name}`;
  return `<svg class="icon${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="${href}"></use></svg>`;
}

export { INLINE, icon };
