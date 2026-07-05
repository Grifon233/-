window.BK = window.BK || {};
(function (BK) {
  let draggedBtnId = null, draggedWinId = null;

  function renderButtons(win, ctx) {
    // Command and input: single auto-connector, no button UI
    if (win.type === "command" || win.type === "input") {
      return buildAutoConnector(win, ctx);
    }

    const wrap = document.createElement("div");
    wrap.className = "btn-list";
    win.buttons.forEach(btn => wrap.appendChild(buildButtonRow(win, btn, ctx)));
    const add = document.createElement("button");
    add.className = "add-btn";
    add.textContent = win.type === "condition" ? "＋ добавить ветку" : "＋ добавить кнопку";
    add.addEventListener("pointerdown", e => e.stopPropagation());
    add.addEventListener("click", () => { ctx.state.addButton(win.id); ctx.rerender(); });
    wrap.appendChild(add);
    enableReorder(win, wrap, ctx);
    return wrap;
  }

  function buildAutoConnector(win, ctx) {
    // Ensure state has exactly one button (the flow exit point)
    if (win.buttons.length === 0) {
      ctx.state.addButton(win.id);
    }
    const btn = win.buttons[0];

    const wrap = document.createElement("div"); wrap.className = "btn-list";
    const holder = document.createElement("div"); holder.className = "btn-row-holder auto-conn-holder";

    const typeClass = win.type === "input" ? "ac-input" : "ac-command";
    const labelText = win.type === "input"
      ? "📥 Когда пользователь напишет — переходит сюда:"
      : "⚡ Когда получена команда — переходит сюда:";

    const row = document.createElement("div");
    row.className = "auto-conn-row " + typeClass;
    row.textContent = labelText;

    const conn = document.createElement("div");
    conn.className = "connector" + (btn.target ? " connected" : "");
    conn.dataset.win = win.id;
    conn.dataset.btn = btn.id;
    conn.title = "Потяните к следующему блоку";
    conn.addEventListener("pointerdown", e => BK.beginLinkDrag(win.id, btn.id, e, ctx));

    holder.append(row, conn);
    wrap.appendChild(holder);
    return wrap;
  }

  function buildButtonRow(win, btn, ctx) {
    const holder = document.createElement("div");
    holder.className = "btn-row-holder";

    const row = document.createElement("div");
    row.className = "tg-btn-row";
    row.dataset.btn = btn.id;

    // drag handle
    const handle = document.createElement("span");
    handle.className = "drag-handle"; handle.textContent = "⠿";
    handle.title = "Перетащите для перестановки"; handle.draggable = true;
    handle.addEventListener("dragstart", e => {
      draggedBtnId = btn.id; draggedWinId = win.id;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", btn.id);
    });
    handle.addEventListener("dragend", () => {
      row.classList.remove("dragging"); draggedBtnId = null; draggedWinId = null;
    });
    handle.addEventListener("pointerdown", e => e.stopPropagation());

    // label
    const label = document.createElement("div");
    label.className = "tg-btn";
    label.contentEditable = "true";
    label.textContent = btn.label;
    label.dataset.placeholder = win.type === "condition" ? "условие / ветка" : "кнопка";
    label.addEventListener("pointerdown", e => e.stopPropagation());
    label.addEventListener("input", () =>
      ctx.state.updateButton(win.id, btn.id, { label: label.innerText.trim() }));

    // action buttons (visible on hover)
    const actions = document.createElement("div");
    actions.className = "btn-actions";

    const gear = document.createElement("span");
    gear.className = "btn-gear"; gear.textContent = "⚙"; gear.title = "Настройки";
    gear.addEventListener("pointerdown", e => e.stopPropagation());

    const del = document.createElement("span");
    del.className = "btn-del"; del.textContent = "✕"; del.title = "Удалить";
    del.addEventListener("pointerdown", e => e.stopPropagation());
    del.addEventListener("click", () => { ctx.state.removeButton(win.id, btn.id); ctx.rerender(); });

    actions.append(gear, del);
    row.append(handle, label, actions);

    // connector — positioned absolutely outside window
    const conn = document.createElement("div");
    conn.className = "connector" + (btn.action === "url" ? " hidden" : "");
    conn.dataset.win = win.id;
    conn.dataset.btn = btn.id;
    conn.title = "Потяните к другому блоку";
    conn.addEventListener("pointerdown", e => BK.beginLinkDrag(win.id, btn.id, e, ctx));

    // settings panel
    const settings = buildSettings(win, btn, ctx, conn);
    gear.addEventListener("click", () => {
      settings.style.display = settings.style.display === "none" ? "flex" : "none";
    });

    holder.append(row, settings, conn);
    return holder;
  }

  function buildSettings(win, btn, ctx, conn) {
    const box = document.createElement("div");
    box.className = "btn-settings"; box.style.display = "none";
    box.addEventListener("pointerdown", e => e.stopPropagation());

    const select = document.createElement("select");
    select.innerHTML =
      '<option value="goto">Переход в другой блок (стрелкой)</option>' +
      '<option value="url">Открыть ссылку (URL)</option>';
    select.value = btn.action;

    const urlInput = document.createElement("input");
    urlInput.type = "text"; urlInput.placeholder = "https://...";
    urlInput.value = btn.url || "";
    urlInput.style.display = btn.action === "url" ? "block" : "none";
    urlInput.addEventListener("input", () =>
      ctx.state.updateButton(win.id, btn.id, { url: urlInput.value.trim() }));

    select.addEventListener("change", () => {
      const action = select.value;
      ctx.state.updateButton(win.id, btn.id, { action, target: action === "url" ? null : btn.target });
      urlInput.style.display = action === "url" ? "block" : "none";
      conn.className = "connector" + (action === "url" ? " hidden" : "");
      ctx.redrawLinks();
    });

    box.append(select, urlInput);
    return box;
  }

  function enableReorder(win, wrap, ctx) {
    wrap.addEventListener("dragover", e => {
      e.preventDefault();
      if (draggedWinId !== win.id) return;
      const rows = [...wrap.querySelectorAll(".tg-btn-row")];
      rows.forEach(r => { r.classList.remove("drag-over"); r.classList.remove("drag-over-bottom"); });
      const after = rows.find(r => {
        const rect = r.getBoundingClientRect();
        return e.clientY < rect.top + rect.height / 2;
      });
      if (after) after.classList.add("drag-over");
      else if (rows.length > 0) rows[rows.length - 1].classList.add("drag-over-bottom");
    });
    wrap.addEventListener("dragleave", () => {
      wrap.querySelectorAll(".tg-btn-row").forEach(r => {
        r.classList.remove("drag-over"); r.classList.remove("drag-over-bottom");
      });
    });
    wrap.addEventListener("drop", e => {
      e.preventDefault();
      if (draggedWinId !== win.id || !draggedBtnId) return;
      const rows = [...wrap.querySelectorAll(".tg-btn-row")];
      const order = rows.map(r => r.dataset.btn).filter(id => id !== draggedBtnId);
      const after = rows.find(r => e.clientY < r.getBoundingClientRect().top + r.getBoundingClientRect().height / 2);
      let idx = after ? order.indexOf(after.dataset.btn) : order.length;
      if (idx < 0) idx = order.length;
      order.splice(idx, 0, draggedBtnId);
      draggedBtnId = null; draggedWinId = null;
      ctx.state.reorderButtons(win.id, order);
      ctx.rerender();
    });
  }

  Object.assign(BK, { renderButtons });
})(window.BK);
