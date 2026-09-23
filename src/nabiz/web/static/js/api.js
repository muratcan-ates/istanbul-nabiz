/* The three ways the page talks to its own server. A failure becomes an Error carrying the HTTP
 * status, so errors.js can title it instead of showing a stack trace. */

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
  });
  let response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' } });
  } catch (err) {
    const offline = new Error('Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.');
    offline.status = 0;
    throw offline;
  }
  let body = null;
  try { body = await response.json(); } catch (err) { body = null; }
  if (!response.ok) {
    const message = (body && body.message) || `İstek başarısız (HTTP ${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    error.kind = body && body.error;
    throw error;
  }
  return body;
}

/**
 * POST a JSON body. Only the alert check uses it: a subscription carries coordinates, and a
 * query string ends up in access logs where a request body does not (docs/privacy.md §4).
 */
async function apiPost(path, payload) {
  let response;
  try {
    response = await fetch(new URL(path, window.location.origin), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const offline = new Error('Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.');
    offline.status = 0;
    throw offline;
  }
  let body = null;
  try { body = await response.json(); } catch (err) { body = null; }
  if (!response.ok) {
    const error = new Error((body && body.message) || `İstek başarısız (HTTP ${response.status}).`);
    error.status = response.status;
    error.kind = body && body.error;
    throw error;
  }
  return body;
}

/** For endpoints the integrator may not have wired yet: a 404 is "not here", not a failure. */
async function probe(path, params) {
  try {
    return await api(path, params);
  } catch (err) {
    if (err.status === 404 || err.status === 405 || err.status === 422 || err.status === 0) return null;
    throw err;
  }
}

export { api, apiPost, probe };
