// A small operator panel. Its server route requires the operator's existing sign-in cookie.
const QUEUE = '/api/console/appeals';

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function jsonResponse(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'İşlem tamamlanamadı.');
  return data;
}

export async function mountConsoleAppeals(root) {
  if (!root) return;
  root.replaceChildren(element('p', 'İtiraz kuyruğu yükleniyor.'));
  try {
    const data = await jsonResponse(await fetch(QUEUE, { credentials: 'same-origin', cache: 'no-store' }));
    const heading = element('h2', 'Kısıt itirazları');
    const notice = element('p', 'Simüle operatör incelemesi. Resmî İBB hizmeti değildir.');
    root.replaceChildren(heading, notice);
    if (!data.appeals.length) {
      root.append(element('p', 'Bekleyen itiraz yok.'));
      return;
    }
    const list = element('ul', '', 'appeal-list');
    for (const appeal of data.appeals) {
      const item = element('li', '', 'appeal-item');
      item.append(element('p', data.categories[appeal.category] || 'İnceleme isteği'));
      item.append(element('p', `Kayıtlı: ${appeal.submitted_at}`));
      const label = element('label', 'Karar gerekçesi');
      const select = document.createElement('select');
      select.setAttribute('aria-label', 'Karar gerekçesi');
      select.append(new Option('Gerekçe seçin', ''));
      for (const [code, text] of Object.entries(data.reasons)) select.append(new Option(text, code));
      label.append(select);
      item.append(label);
      const message = element('p', '', 'appeal-message');
      message.setAttribute('role', 'status');
      for (const [action, title] of [['reopen', 'Geri aç'], ['uphold', 'Kısıtı sürdür']]) {
        const button = element('button', title);
        button.type = 'button';
        button.addEventListener('click', async () => {
          if (!select.value) {
            message.textContent = 'Önce karar gerekçesi seçin.';
            return;
          }
          button.disabled = true;
          try {
            const response = await fetch(`${QUEUE}/${encodeURIComponent(appeal.id)}/decision`, {
              method: 'POST', credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action, reason: select.value }),
            });
            await jsonResponse(response);
            await mountConsoleAppeals(root);
          } catch (error) {
            message.textContent = error.message || 'Karar kaydedilemedi.';
            button.disabled = false;
          }
        });
        item.append(button);
      }
      item.append(message);
      list.append(item);
    }
    root.append(list);
  } catch (error) {
    root.replaceChildren(element('p', error.message || 'İtiraz kuyruğu açılamadı.'));
  }
}

const appealRoot = document.getElementById('appeals');
if (appealRoot) void mountConsoleAppeals(appealRoot);
