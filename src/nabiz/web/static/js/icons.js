/* Every icon goes through icon(name): the sprite in index.html holds the symbols, callers only
 * name them. Pure. */

function icon(name, cls) {
  return `<svg class="icon${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

export { icon };
