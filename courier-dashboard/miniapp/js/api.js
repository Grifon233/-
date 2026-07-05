// Связь с backend. Если приложение открыто как файл/с другого порта — берём localhost.
window.API = (function () {
  const sameOrigin = location.protocol === 'http:' || location.protocol === 'https:';
  const BASE = sameOrigin ? '' : 'http://127.0.0.1:8000';

  async function getStreets(cityName) {
    const r = await fetch(`${BASE}/streets?city=${encodeURIComponent(cityName)}`);
    if (!r.ok) throw new Error(`streets ${r.status}`);
    return r.json();
  }

  async function getStreet(streetId) {
    const r = await fetch(`${BASE}/streets/${encodeURIComponent(streetId)}`);
    if (!r.ok) throw new Error(`street ${r.status}`);
    return r.json();
  }

  async function sendFeedback(payload) {
    const r = await fetch(`${BASE}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(`feedback ${r.status}`);
    return r.json();
  }

  return { BASE, getStreets, getStreet, sendFeedback };
})();
