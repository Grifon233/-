// Контроллер приложения: экраны, карта, смена города, статус, обратная связь.
(function () {
  'use strict';

  // --- Telegram Mini App (безопасно работает и вне Telegram) ---
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }

  // --- DOM ---
  const $ = (id) => document.getElementById(id);
  const screenCity = $('screen-city');
  const screenMap = $('screen-map');
  const cityList = $('city-list');
  const currentCityName = $('current-city-name');
  const statusChip = $('status-chip');
  const statusText = $('status-text');
  const feedbackModal = $('feedback-modal');
  const feedbackText = $('feedback-text');
  const toastEl = $('toast');

  let map = null;
  let streetsLayer = null;
  let currentCity = null;
  let streetsRequest = 0;

  // --- Экран выбора города ---
  function renderCities() {
    cityList.innerHTML = '';
    (window.CITIES || []).forEach((city) => {
      const card = document.createElement('button');
      card.className = 'city-card';
      card.setAttribute('role', 'listitem');
      card.dataset.city = city.id;
      card.innerHTML =
        `<span class="city-emoji">${city.emoji}</span>` +
        `<span class="city-info"><span class="city-name">${city.name}</span>` +
        `<span class="city-pop">${city.pop}</span></span>` +
        `<span class="city-arrow">›</span>`;
      card.addEventListener('click', () => selectCity(city));
      cityList.appendChild(card);
    });
  }

  function showCityScreen() {
    screenMap.classList.add('hidden');
    screenCity.classList.remove('hidden');
  }

  // --- Выбор города -> карта ---
  function selectCity(city) {
    currentCity = city;
    try { localStorage.setItem('city', city.id); } catch (e) {}
    currentCityName.textContent = city.name;

    screenCity.classList.add('hidden');
    screenMap.classList.remove('hidden');

    ensureMap();
    map.setView([city.lat, city.lng], city.zoom);
    setTimeout(() => map.invalidateSize(), 60); // карта стала видимой
    loadStreets(city);
  }

  // --- Карта (Leaflet + OpenStreetMap) ---
  function ensureMap() {
    if (map) return;
    map = L.map('map', { zoomControl: true, attributionControl: true });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap',
    }).addTo(map);
    streetsLayer = L.layerGroup().addTo(map);
  }

  // --- Загрузка занятых улиц + статус ---
  async function loadStreets(city) {
    const requestId = ++streetsRequest;
    setStatus('ok', 'Загрузка…');
    try {
      const streets = await window.API.getStreets(city.name);
      if (requestId !== streetsRequest || currentCity !== city) return;
      streetsLayer.clearLayers();
      let drawn = 0;
      streets.forEach((s) => {
        if (s.geometry) { drawStreet(s); drawn++; }
      });
      if (streets.length === 0) {
        setStatus('ok', 'Занятых улиц нет');
      } else if (drawn === 0) {
        setStatus('error', `Найдено улиц: ${streets.length}, геометрия недоступна`);
      } else if (drawn < streets.length) {
        setStatus('ok', `На карте: ${drawn} из ${streets.length}`);
      } else {
        setStatus('ok', `Занятых улиц: ${streets.length}`);
      }
    } catch (e) {
      if (requestId !== streetsRequest || currentCity !== city) return;
      setStatus('error', 'Нет связи с сервером');
    }
  }

  function drawStreet(s) {
    // s.geometry — GeoJSON LineString (появится на Этапе 2 backend).
    const line = L.geoJSON(s.geometry, { style: { color: '#e23b3b', weight: 6, opacity: 0.85 } });
    const quotes = (s.quotes || [])
      .map((q) => {
        const link = safeLink(q.link);
        const source = link
          ? `<br><a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">источник</a>`
          : '';
        return `<div class="quote">${escapeHtml(q.text)}${source}</div>`;
      })
      .join('');
    line.bindPopup(`<b>${escapeHtml(s.street)}</b>${quotes}`);
    line.addTo(streetsLayer);
  }

  function setStatus(kind, text) {
    statusChip.className = 'status-chip ' + (kind === 'error' ? 'status-error' : 'status-ok');
    statusText.textContent = text;
  }

  // --- Обратная связь ---
  function openFeedback() { feedbackModal.classList.remove('hidden'); feedbackText.focus(); }
  function closeFeedback() { feedbackModal.classList.add('hidden'); }

  async function sendFeedback() {
    const text = feedbackText.value.trim();
    if (!text) { toast('Напишите сообщение', 'error'); return; }
    const sendBtn = $('fb-send');
    sendBtn.disabled = true;
    try {
      const user = tg && tg.initDataUnsafe && tg.initDataUnsafe.user
        ? `${tg.initDataUnsafe.user.first_name || ''} (id ${tg.initDataUnsafe.user.id})`
        : null;
      const res = await window.API.sendFeedback({
        text,
        city: currentCity ? currentCity.name : null,
        source: 'miniapp',
        user,
      });
      if (res.sent) {
        toast('Сообщение отправлено. Спасибо!', 'ok');
        feedbackText.value = '';
        closeFeedback();
      } else if (res.reason === 'feedback_bot_not_configured') {
        toast('Канал обратной связи ещё не настроен', 'error');
      } else {
        toast('Не удалось отправить, попробуйте позже', 'error');
      }
    } catch (e) {
      toast('Нет связи с сервером', 'error');
    } finally {
      sendBtn.disabled = false;
    }
  }

  // --- Тост ---
  let toastTimer = null;
  function toast(msg, kind) {
    toastEl.textContent = msg;
    toastEl.className = 'toast ' + (kind === 'error' ? 'toast-error' : kind === 'ok' ? 'toast-ok' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.add('hidden'), 3200);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function safeLink(value) {
    try {
      const url = new URL(String(value), location.origin);
      return ['http:', 'https:', 'tg:'].includes(url.protocol) ? url.href : null;
    } catch (e) {
      return null;
    }
  }

  // --- Привязка событий ---
  $('btn-change-city').addEventListener('click', showCityScreen);
  $('btn-feedback').addEventListener('click', openFeedback);
  $('fb-cancel').addEventListener('click', closeFeedback);
  $('fb-send').addEventListener('click', sendFeedback);
  feedbackModal.addEventListener('click', (e) => { if (e.target === feedbackModal) closeFeedback(); });

  // --- Старт: всегда показываем выбор города ---
  renderCities();
  let savedCity = null;
  try {
    const savedId = localStorage.getItem('city');
    savedCity = (window.CITIES || []).find((city) => city.id === savedId);
  } catch (e) {}
  if (savedCity) selectCity(savedCity);
  else showCityScreen();
})();
