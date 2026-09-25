/* icon(name): every glyph a script renders comes from /icons.svg (one cached request); the static
 * markup inlines its own. Every icon is aria-hidden; the word beside it carries the meaning. Pure. */

function icon(name, cls) {
  return `<svg class="icon${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="/icons.svg#i-${name}"></use></svg>`;
}

export { icon };
