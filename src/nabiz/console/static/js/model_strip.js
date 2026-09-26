/* Give the citizen one plain explanation only when model availability changes the answer path. */

import { MOCK, get } from './api.js';
import { REFRESH_MS } from './config.js';
import { esc } from './format.js';
import { icon } from './icons.js';

const anchor = document.querySelector('#chat-hint');
let note = document.querySelector('#model-note');
let timer = null;
/* The sentence on screen now; unchanged text is not rewritten, so a screen reader hears it once. */
let shown = '';

if (anchor && !note) {
  note = document.createElement('p');
  note.id = 'model-note';
  note.className = 'chat-hint model-note';
  note.setAttribute('role', 'status');
  note.hidden = true;
  anchor.after(note);
}

async function load() {
  if (!note) return;
  let sentence = '';
  if (!MOCK) {
    try {
      const status = await get('/api/model/status');
      sentence = status.note || '';
    } catch {
      sentence = '';
    }
  }
  if (sentence === shown) return;
  shown = sentence;
  if (sentence) note.innerHTML = icon('info-circle') + ' ' + esc(sentence);
  else note.textContent = '';
  note.hidden = !sentence;
}

if (note) {
  const stop = () => { clearInterval(timer); timer = null; };
  const start = () => {
    stop();
    if (document.visibilityState === 'hidden') return;
    load();
    timer = setInterval(load, REFRESH_MS);
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') stop();
    else start();
  });
  start();
}
