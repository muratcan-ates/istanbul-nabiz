/* Scripted motion lives here so prefers-reduced-motion stops it too: CSS cannot, because an
 * explicit behavior: 'smooth' beats scroll-behavior: auto (check_web_budget.py, motion). */

const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

function scrollToElement(el, block) {
  el.scrollIntoView({ block, behavior: reduce.matches ? 'auto' : 'smooth' });
}

function easeMap(map, options) {
  map.easeTo({ ...options, duration: reduce.matches ? 0 : options.duration });
}

export { scrollToElement, easeMap };
