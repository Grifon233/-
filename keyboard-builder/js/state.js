window.BK = window.BK || {};
(function (BK) {
  const STORAGE_KEY = "bot-logic";
  let state = { version: 2, windows: [] };
  let idCounter = 1;

  function getState() { return state; }
  function genId(p) { return `${p||"id"}_${Date.now().toString(36)}_${idCounter++}`; }
  function getWindow(id) { return state.windows.find(w => w.id === id); }

  function addWindow(x, y, type) {
    const t = type || "message";
    const defaults = {
      message:   { title: "Сообщение",    image: null, text: "", buttons: [] },
      command:   { title: "/start",        command: "/start", buttons: [
        { id: genId("b"), label: "", action: "goto", target: null, url: "", row: 0 },
      ]},
      condition: { title: "Условие",       condition_text: "", buttons: [
        { id: genId("b"), label: "Да ✓",  action: "goto", target: null, url: "", row: 0 },
        { id: genId("b"), label: "Нет ✕", action: "goto", target: null, url: "", row: 1 },
      ]},
      input:     { title: "Ожидание ввода", variable_name: "user_input", text: "", image: null, buttons: [
        { id: genId("b"), label: "Далее →", action: "goto", target: null, url: "", row: 0 },
      ]},
      delay:     { title: "Задержка",      delay_seconds: 3, buttons: [
        { id: genId("b"), label: "Далее →", action: "goto", target: null, url: "", row: 0 },
      ]},
      variable:  { title: "Переменная",    variable_name: "my_var", variable_value: "", buttons: [
        { id: genId("b"), label: "Далее →", action: "goto", target: null, url: "", row: 0 },
      ]},
      api:       { title: "HTTP-запрос",   api_url: "", api_method: "GET", api_save_to: "", buttons: [
        { id: genId("b"), label: "✓ Успешно", action: "goto", target: null, url: "", row: 0 },
        { id: genId("b"), label: "✕ Ошибка",  action: "goto", target: null, url: "", row: 1 },
      ]},
    };
    const win = Object.assign(
      { id: genId("w"), x: x||100, y: y||100, type: t, note: "" },
      defaults[t] || defaults.message
    );
    state.windows.push(win);
    saveLocal();
    return win;
  }

  function removeWindow(id) {
    state.windows = state.windows.filter(w => w.id !== id);
    state.windows.forEach(w => w.buttons.forEach(b => { if (b.target === id) b.target = null; }));
    saveLocal();
  }
  function updateWindow(id, patch) {
    const w = getWindow(id); if (w) Object.assign(w, patch); saveLocal();
  }

  function addButton(winId) {
    const w = getWindow(winId); if (!w) return null;
    const btn = { id: genId("b"), label: "Кнопка", action: "goto", target: null, url: "", row: w.buttons.length };
    w.buttons.push(btn); saveLocal(); return btn;
  }
  function updateButton(winId, btnId, patch) {
    const w = getWindow(winId); if (!w) return;
    const b = w.buttons.find(b => b.id === btnId); if (b) Object.assign(b, patch); saveLocal();
  }
  function removeButton(winId, btnId) {
    const w = getWindow(winId); if (!w) return;
    w.buttons = w.buttons.filter(b => b.id !== btnId);
    w.buttons.forEach((b,i) => b.row = i); saveLocal();
  }
  function reorderButtons(winId, orderedIds) {
    const w = getWindow(winId); if (!w) return;
    const map = new Map(w.buttons.map(b => [b.id, b]));
    w.buttons = orderedIds.map(id => map.get(id)).filter(Boolean);
    w.buttons.forEach((b,i) => b.row = i); saveLocal();
  }

  function saveLocal() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch(e){}
  }
  function loadLocal() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) { const p = JSON.parse(raw); if (p && Array.isArray(p.windows)) state = p; }
    } catch(e){}
  }
  function replaceState(ns) {
    if (ns && Array.isArray(ns.windows)) { state = Object.assign({version:2}, ns); saveLocal(); }
  }

  Object.assign(BK, {
    getState, genId, getWindow,
    addWindow, removeWindow, updateWindow,
    addButton, updateButton, removeButton, reorderButtons,
    saveLocal, loadLocal, replaceState,
  });
})(window.BK);
