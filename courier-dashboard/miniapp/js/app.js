// Контроллер экранов, карты, статуса улиц и обратной связи.
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const cities = window.CITIES || [];
  const screenCity = $('screen-city');
  const screenMap = $('screen-map');
  const cityList = $('city-list');
  const cityName = $('current-city-name');
  const refreshButton = $('btn-refresh');
  const feedbackButton = $('btn-feedback');
  const statusChip = $('status-chip');
  const statusText = $('status-text');
  const mapEl = $('map');
  const mapNote = $('map-note');
  const streetPanel = $('street-panel');
  const streetList = $('street-list');
  const streetSummary = $('street-summary');
  const feedbackModal = $('feedback-modal');
  const feedbackText = $('feedback-text');
  const feedbackError = $('feedback-error');
  const sendButton = $('fb-send');
  const toastEl = $('toast');
  const refreshInterval = 60000;

  let tg = null;
  let map = null;
  let tileLayer = null;
  let streetsLayer = null;
  let tileProblem = false;
  let batchTileProblem = false;
  let currentCity = null;
  let streetRequest = null;
  let refreshTimer = null;
  let lastAttemptAt = 0;
  let hasSnapshot = false;
  let feedbackPending = false;
  let toastTimer = null;
  const displayedStreets = new Map();

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function renderCities() {
    for (const city of cities) {
      const card = element('button', null, 'city-card');
      card.type = 'button';
      card.dataset.city = city.id;
      const emoji = element('span', city.emoji, 'city-emoji');
      const arrow = element('span', '›', 'city-arrow');
      emoji.setAttribute('aria-hidden', 'true');
      arrow.setAttribute('aria-hidden', 'true');
      const info = element('span', null, 'city-info');
      info.append(element('span', city.name, 'city-name'), element('span', city.pop, 'city-pop'));
      card.append(emoji, info, arrow);
      card.addEventListener('click', () => selectCity(city));
      const item = element('li');
      item.append(card);
      cityList.append(item);
    }
  }

  function showCityScreen() {
    const previous = currentCity;
    currentCity = null;
    stopStreetRequests();
    screenMap.hidden = true;
    screenCity.hidden = false;
    syncTelegramBack();
    if (previous) {
      const previousCard = [...cityList.querySelectorAll('button')].find((card) => card.dataset.city === previous.id);
      (previousCard || $('city-title')).focus();
    }
  }

  function selectCity(city, focus = true) {
    if (currentCity === city) return;
    stopStreetRequests();
    currentCity = city;
    try { localStorage.setItem('city', city.id); } catch (error) {}
    cityName.textContent = city.name;
    screenCity.hidden = true;
    screenMap.hidden = false;
    if (focus) cityName.focus({ preventScroll: true });
    resetStreets();
    tileProblem = false;
    setMapNote('');
    if (ensureMap()) {
      map.invalidateSize();
      map.setView([city.lat, city.lng], city.zoom, { animate: false });
    }
    syncTelegramBack();
    loadStreets({ initial: true });
  }

  function initTelegram() {
    if (tg || !window.Telegram?.WebApp) return;
    tg = window.Telegram.WebApp;
    try {
      tg.ready();
      tg.expand();
      tg.BackButton?.onClick(() => {
        if (feedbackModal.open) closeFeedback();
        else if (currentCity) showCityScreen();
      });
      syncTelegramBack();
    } catch (error) { /* Сайт остаётся доступным без Telegram SDK. */ }
  }

  function syncTelegramBack() {
    try {
      if (currentCity) tg?.BackButton?.show();
      else tg?.BackButton?.hide();
    } catch (error) {}
  }

  function setMapNote(message) {
    if (mapNote.textContent !== message) mapNote.textContent = message;
  }

  function ensureMap() {
    if (map) return true;
    if (!window.L) {
      mapEl.hidden = true;
      setMapNote('Карта недоступна. Отметки остаются доступны в списке.');
      return false;
    }
    try {
      mapEl.hidden = false;
      map = L.map(mapEl, { zoomControl: true, attributionControl: true });
      tileLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>',
      });
      tileLayer.on('loading', () => { batchTileProblem = false; });
      tileLayer.on('tileerror', () => {
        batchTileProblem = true;
        tileProblem = true;
        if (currentCity) setMapNote('Не удалось загрузить часть карты. Попробуйте обновить.');
      });
      tileLayer.on('load', () => {
        if (!currentCity || batchTileProblem) return;
        tileProblem = false;
        setMapNote('');
      });
      tileLayer.addTo(map);
      streetsLayer = L.layerGroup().addTo(map);
      if (typeof ResizeObserver === 'function') {
        const observer = new ResizeObserver(() => {
          if (currentCity) map.invalidateSize({ debounceMoveend: true });
        });
        observer.observe(mapEl);
      }
      return true;
    } catch (error) {
      map?.remove();
      map = null;
      tileLayer = null;
      streetsLayer = null;
      mapEl.hidden = true;
      setMapNote('Карта недоступна. Отметки остаются доступны в списке.');
      return false;
    }
  }

  function stopStreetRequests() {
    clearTimeout(refreshTimer);
    streetRequest?.abort();
    streetRequest = null;
    refreshButton.removeAttribute('aria-disabled');
    refreshButton.textContent = 'Обновить';
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    if (!currentCity || document.hidden || streetRequest) return;
    refreshTimer = setTimeout(loadStreets, Math.max(0, refreshInterval - (Date.now() - lastAttemptAt)));
  }

  function resetStreets() {
    hasSnapshot = false;
    map?.closePopup();
    streetsLayer?.clearLayers();
    displayedStreets.clear();
    streetList.replaceChildren();
    streetPanel.open = false;
    streetPanel.hidden = true;
  }

  function setStatus(kind, message) {
    statusChip.className = 'status-chip status-' + kind;
    if (statusText.textContent !== message) statusText.textContent = message;
  }

  async function loadStreets({ initial = false, manual = false } = {}) {
    if (!currentCity || streetRequest) return;
    clearTimeout(refreshTimer);
    const request = new AbortController();
    const city = currentCity;
    streetRequest = request;
    lastAttemptAt = Date.now();
    refreshButton.setAttribute('aria-disabled', 'true');
    if (manual) {
      refreshButton.textContent = 'Обновляем…';
      if (tileProblem && map) tileLayer.redraw();
    }
    if (initial || (!hasSnapshot && manual)) setStatus('loading', 'Загрузка…');

    try {
      const rows = await window.API.getStreets(city.name, request.signal);
      if (request !== streetRequest || currentCity !== city) return;
      if (!Array.isArray(rows)) throw Object.assign(new Error('Invalid streets'), { code: 'invalid_response' });

      const streets = normalizeStreets(rows);
      if (rows.length && !streets.length) {
        throw Object.assign(new Error('Invalid street rows'), { code: 'invalid_response' });
      }
      const drawn = renderStreets(streets);
      hasSnapshot = true;
      if (streets.length === 0) {
        setStatus('ok', 'Занятых улиц нет');
      } else if (drawn === 0) {
        setStatus('warning', 'Занятых улиц: ' + streets.length + '. Отметки только в списке.');
      } else if (drawn < streets.length) {
        setStatus('warning', 'На карте: ' + drawn + ' из ' + streets.length + '. Все улицы есть в списке.');
      } else {
        setStatus('ok', 'Занятых улиц: ' + streets.length);
      }
    } catch (error) {
      if (request !== streetRequest || currentCity !== city) return;
      let message = 'Нет связи с сервером.';
      if (error?.code === 'invalid_response') message = 'Сервер вернул некорректные данные.';
      else if (error?.code === 'timeout') message = 'Сервер не ответил вовремя.';
      else if (error?.status) message = 'Не удалось загрузить данные с сервера.';
      setStatus('error', message + (hasSnapshot ? ' Показаны последние данные.' : ' Попробуйте обновить.'));
    } finally {
      if (request === streetRequest) {
        streetRequest = null;
        refreshButton.removeAttribute('aria-disabled');
        refreshButton.textContent = 'Обновить';
        scheduleRefresh();
      }
    }
  }

  function normalizeStreets(rows) {
    const items = new Map();
    for (const row of rows) {
      if (!row || typeof row.id !== 'string' || !row.id ||
          typeof row.street !== 'string' || !row.street.trim() || row.active === false || items.has(row.id)) continue;
      const quotes = (Array.isArray(row.quotes) ? row.quotes : [])
        .filter((quote) => quote && typeof quote.text === 'string' && quote.text.trim())
        .map((quote) => ({ text: quote.text, link: safeLink(quote.link) }));
      items.set(row.id, { id: row.id, name: row.street.trim(), geometry: lineGeometry(row.geometry), quotes });
    }
    return [...items.values()];
  }

  function lineGeometry(geometry) {
    if (!geometry) return null;
    const validPoint = (point) => Array.isArray(point) && Number.isFinite(point[0]) &&
      Number.isFinite(point[1]) && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90;
    const validLine = (line) => Array.isArray(line) && line.length >= 2 && line.every(validPoint);
    const { type, coordinates } = geometry;
    if (type === 'LineString' && validLine(coordinates)) return { type, coordinates };
    if (type === 'MultiLineString' && Array.isArray(coordinates) && coordinates.length &&
        coordinates.every(validLine)) return { type, coordinates };
    return null;
  }

  function renderStreets(streets) {
    const nextIds = new Set(streets.map((street) => street.id));
    const wasHidden = streetPanel.hidden;
    streetPanel.hidden = streets.length === 0;
    const summaryText = 'Список улиц (' + streets.length + ')';
    if (streets.length && streetSummary.textContent !== summaryText) streetSummary.textContent = summaryText;
    let drawn = 0;
    for (const [id, existing] of displayedStreets) {
      if (nextIds.has(id)) continue;
      if (existing.item.contains(document.activeElement)) {
        (streets.length ? streetSummary : refreshButton).focus();
      }
      existing.item.remove();
      if (existing.layer) streetsLayer.removeLayer(existing.layer);
      displayedStreets.delete(id);
    }

    for (const street of streets) {
      const geometryKey = JSON.stringify(street.geometry);
      const contentKey = JSON.stringify([street.name, street.quotes]);
      const before = displayedStreets.get(street.id);
      let layer = before?.geometryKey === geometryKey ? before.layer : null;
      if (before?.layer && before.layer !== layer) streetsLayer.removeLayer(before.layer);
      if (street.geometry && map && !layer) {
        layer = L.geoJSON(street.geometry, {
          style: { color: '#c8203e', weight: 6, opacity: 0.9 },
        });
        layer.bindPopup(popupContent(street)).addTo(streetsLayer);
      } else if (layer && before.contentKey !== contentKey) {
        layer.setPopupContent(popupContent(street));
      }
      if (layer) drawn++;

      let item = before?.item;
      if (!item || before.contentKey !== contentKey || before.layer !== layer) {
        const isExpanded = item?.firstElementChild.open;
        const hadFocus = item?.contains(document.activeElement);
        const updatedItem = streetItem(street, layer);
        updatedItem.firstElementChild.open = Boolean(isExpanded);
        if (item) item.replaceWith(updatedItem);
        else streetList.append(updatedItem);
        item = updatedItem;
        if (hadFocus) item.querySelector('summary').focus();
      }
      displayedStreets.set(street.id, { geometryKey, contentKey, layer, item });
    }
    if (wasHidden && drawn === 0 && streets.length) streetPanel.open = true;
    else if (!streets.length) streetPanel.open = false;
    return drawn;
  }

  function streetItem(street, layer) {
    const item = element('li');
    const details = element('details');
    const summary = element('summary', street.name);
    if (!layer) summary.append(element('span', ' — без отметки на карте', 'street-unmapped'));
    details.append(summary);
    const content = element('div', null, 'street-content');
    content.append(quotesContent(street.quotes));
    if (layer) {
      const showButton = element('button', 'Показать на карте', 'control');
      showButton.type = 'button';
      showButton.addEventListener('click', () => {
        streetPanel.open = false;
        map.invalidateSize();
        map.fitBounds(layer.getBounds(), { padding: [32, 32], maxZoom: 16, animate: false });
        mapEl.focus({ preventScroll: true });
        layer.openPopup();
      });
      content.append(showButton);
    }
    details.append(content);
    item.append(details);
    return item;
  }

  function popupContent(street) {
    const popup = element('div');
    popup.append(element('strong', street.name), quotesContent(street.quotes));
    return popup;
  }

  function quotesContent(quotes) {
    const node = element('div');
    if (!quotes.length) node.append(element('p', 'Цитаты недоступны.', 'quote'));
    for (const quote of quotes) {
      const item = element('div', quote.text, 'quote');
      if (quote.link) {
        const source = element('a', 'Открыть источник');
        source.href = quote.link;
        source.target = '_blank';
        source.rel = 'noopener noreferrer';
        item.append(document.createElement('br'), source);
      }
      node.append(item);
    }
    return node;
  }

  function safeLink(value) {
    if (typeof value !== 'string') return null;
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch (error) {
      return null;
    }
  }

  function openFeedback() {
    if (feedbackModal.open) return;
    clearTimeout(toastTimer);
    toastEl.classList.add('hidden');
    feedbackModal.showModal();
    feedbackText.focus();
  }

  function closeFeedback() {
    if (feedbackModal.open) feedbackModal.close();
  }

  function setFeedbackError(message, invalid = false) {
    feedbackError.textContent = message;
    if (invalid) feedbackText.setAttribute('aria-invalid', 'true');
    else feedbackText.removeAttribute('aria-invalid');
  }

  async function sendFeedback(event) {
    event.preventDefault();
    if (feedbackPending) return;
    const text = feedbackText.value.trim();
    if (!text) {
      setFeedbackError('Напишите сообщение.', true);
      feedbackText.focus();
      return;
    }
    feedbackPending = true;
    feedbackText.readOnly = true;
    sendButton.setAttribute('aria-disabled', 'true');
    sendButton.textContent = 'Отправляем…';
    setFeedbackError('');
    let failure = '';
    try {
      const result = await window.API.sendFeedback({ text, city: currentCity?.name ?? null, source: 'miniapp' });
      if (result?.sent === true) {
        feedbackText.value = '';
        closeFeedback();
        toast('Сообщение отправлено. Спасибо!', 'ok');
      } else if (result?.reason === 'feedback_bot_not_configured') {
        failure = 'Канал обратной связи ещё не настроен.';
      } else if (result?.reason === 'rate_limited') {
        failure = 'Слишком много сообщений. Попробуйте через минуту.';
      } else {
        failure = 'Не удалось отправить сообщение. Попробуйте позже.';
      }
    } catch (error) {
      if (error?.status === 429) failure = 'Слишком много сообщений. Попробуйте через минуту.';
      else if (error?.code === 'timeout') failure = 'Сервер не подтвердил отправку вовремя. Сообщение могло быть доставлено.';
      else if (error?.status || error?.code === 'invalid_response') failure = 'Не удалось отправить сообщение. Попробуйте позже.';
      else failure = 'Нет связи с сервером. Текст сохранён в форме.';
    } finally {
      feedbackPending = false;
      feedbackText.readOnly = false;
      sendButton.removeAttribute('aria-disabled');
      sendButton.textContent = 'Отправить';
      if (failure) {
        setFeedbackError(failure);
        if (!feedbackModal.open) toast(failure, 'error');
      }
    }
  }

  function toast(message, kind) {
    toastEl.className = 'toast toast-' + kind;
    toastEl.textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.add('hidden'), 5000);
  }

  $('btn-change-city').addEventListener('click', showCityScreen);
  refreshButton.addEventListener('click', () => loadStreets({ manual: true }));
  feedbackButton.addEventListener('click', openFeedback);
  $('fb-cancel').addEventListener('click', closeFeedback);
  $('feedback-form').addEventListener('submit', sendFeedback);
  feedbackText.addEventListener('input', () => setFeedbackError(''));
  feedbackModal.addEventListener('close', () => feedbackButton.focus());
  feedbackModal.addEventListener('click', (event) => {
    if (event.target === feedbackModal) closeFeedback();
  });
  document.addEventListener('visibilitychange', scheduleRefresh);
  $('telegram-sdk').addEventListener('load', initTelegram, { once: true });

  renderCities();
  initTelegram();
  let savedCity = null;
  try {
    const savedId = localStorage.getItem('city');
    savedCity = cities.find((city) => city.id === savedId);
  } catch (error) {}
  if (savedCity) selectCity(savedCity, false);
})();
