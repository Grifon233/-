// Со страницы /app/ используем тот же сервер; для file: — локальный FastAPI.
window.API = (function () {
  'use strict';
  const sameOrigin = location.protocol === 'http:' || location.protocol === 'https:';
  const BASE = sameOrigin ? '' : 'http://127.0.0.1:8000';

  async function request(path, { signal, timeout = 12000, ...options } = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    else signal?.addEventListener('abort', abort, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; abort(); }, timeout);
    try {
      const response = await fetch(BASE + path, { ...options, signal: controller.signal });
      if (!response.ok) throw Object.assign(new Error('HTTP ' + response.status), { status: response.status });
      try {
        return await response.json();
      } catch (error) {
        if (controller.signal.aborted) throw error;
        throw Object.assign(new Error('Invalid API response'), { code: 'invalid_response' });
      }
    } catch (error) {
      if (timedOut) throw Object.assign(new Error('Request timed out'), { code: 'timeout' });
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  function getStreets(cityName, signal) {
    const query = new URLSearchParams({ city: cityName });
    return request('/streets?' + query, { signal, cache: 'no-store' });
  }

  function getStreet(streetId, signal) {
    return request('/streets/' + encodeURIComponent(streetId), { signal, cache: 'no-store' });
  }

  function sendFeedback(payload) {
    return request('/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      timeout: 20000,
    });
  }

  return { getStreets, getStreet, sendFeedback };
})();
