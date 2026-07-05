window.BK = window.BK || {};
(function (BK) {
  const TYPE_META = {
    message:   { icon: "📨", color: "var(--c-message)"   },
    command:   { icon: "⚡", color: "var(--c-command)"   },
    condition: { icon: "🔀", color: "var(--c-condition)" },
    input:     { icon: "⌨️", color: "var(--c-input)"     },
    delay:     { icon: "⏳", color: "var(--c-delay)"     },
    variable:  { icon: "📦", color: "var(--c-variable)"  },
    api:       { icon: "🌐", color: "var(--c-api)"       },
  };

  function renderWindow(win, ctx) {
    const el = document.createElement("div");
    el.className = `window type-${win.type || "message"}`;
    el.dataset.win = win.id;
    el.style.left = win.x + "px";
    el.style.top  = win.y + "px";

    el.appendChild(buildHead(win, el, ctx));
    const body = document.createElement("div");
    body.className = "win-body";

    // type-specific fields
    const tf = buildTypeFields(win, ctx);
    if (tf) body.appendChild(tf);

    if (win.type === "message") {
      body.appendChild(buildImage(win, ctx));
      body.appendChild(buildText(win, ctx));
    }
    if (win.type === "input") {
      body.appendChild(buildText(win, ctx));
    }

    body.appendChild(BK.renderButtons(win, ctx));
    body.appendChild(buildNote(win, ctx));
    el.appendChild(body);
    return el;
  }

  function buildHead(win, el, ctx) {
    const meta = TYPE_META[win.type] || TYPE_META.message;
    const head = document.createElement("div");
    head.className = "win-head";

    const grip = document.createElement("span");
    grip.className = "win-grip"; grip.textContent = "⠿⠿"; grip.title = "Перетащить блок";

    const icon = document.createElement("span");
    icon.className = "win-type-icon"; icon.textContent = meta.icon;

    const titleWrap = document.createElement("div");
    titleWrap.className = "win-title-wrap";
    const lbl = document.createElement("div");
    lbl.className = "win-title-label"; lbl.textContent = "только для вас";
    const title = document.createElement("div");
    title.className = "win-title"; title.contentEditable = "true";
    title.textContent = win.title;
    title.addEventListener("pointerdown", e => e.stopPropagation());
    title.addEventListener("input", () => ctx.state.updateWindow(win.id, { title: title.innerText.trim() }));
    titleWrap.append(lbl, title);

    const del = document.createElement("div");
    del.className = "win-del"; del.textContent = "✕"; del.title = "Удалить блок";
    del.addEventListener("pointerdown", e => e.stopPropagation());
    del.addEventListener("click", () => { if (confirm("Удалить этот блок?")) { ctx.state.removeWindow(win.id); ctx.rerender(); } });

    head.append(grip, icon, titleWrap, del);
    enableWindowDrag(win, el, head, ctx);
    return head;
  }

  function buildTypeFields(win, ctx) {
    const box = document.createElement("div");
    if (win.type === "command") {
      const f = typeField("Команда:", "text", win.command || "/start", v => {
        ctx.state.updateWindow(win.id, { command: v });
      }, "/start");
      box.appendChild(f);
      return box;
    }
    if (win.type === "condition") {
      const f = typeField("Если:", "text", win.condition_text || "", v => {
        ctx.state.updateWindow(win.id, { condition_text: v });
      }, "опишите условие…");
      box.appendChild(f);
      return box;
    }
    if (win.type === "input") {
      const f = typeField("Сохранить в:", "text", win.variable_name || "", v => {
        ctx.state.updateWindow(win.id, { variable_name: v });
      }, "имя_переменной");
      box.appendChild(f);
      return box;
    }
    if (win.type === "delay") {
      const f = typeField("Ждать (сек):", "number", win.delay_seconds || 3, v => {
        ctx.state.updateWindow(win.id, { delay_seconds: Math.max(1, parseInt(v) || 1) });
      }, "3");
      box.appendChild(f);
      return box;
    }
    if (win.type === "variable") {
      box.appendChild(typeField("Переменная:", "text", win.variable_name || "", v =>
        ctx.state.updateWindow(win.id, { variable_name: v }), "имя_переменной"));
      box.appendChild(typeField("Значение:", "text", win.variable_value || "", v =>
        ctx.state.updateWindow(win.id, { variable_value: v }), "текст или {{другая_переменная}}"));
      return box;
    }
    if (win.type === "api") {
      box.appendChild(typeField("URL:", "text", win.api_url || "", v =>
        ctx.state.updateWindow(win.id, { api_url: v }), "https://api.example.com/data"));
      box.appendChild(typeFieldSelect("Метод:", ["GET","POST","PUT","DELETE"], win.api_method || "GET", v =>
        ctx.state.updateWindow(win.id, { api_method: v })));
      box.appendChild(typeField("Сохранить в:", "text", win.api_save_to || "", v =>
        ctx.state.updateWindow(win.id, { api_save_to: v }), "имя_переменной (необязательно)"));
      return box;
    }
    return null;
  }

  function typeFieldSelect(labelText, options, value, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "type-field";
    const lbl = document.createElement("label"); lbl.textContent = labelText;
    const sel = document.createElement("select");
    options.forEach(o => { const opt = document.createElement("option"); opt.value = o; opt.textContent = o; sel.appendChild(opt); });
    sel.value = value;
    sel.addEventListener("pointerdown", e => e.stopPropagation());
    sel.addEventListener("change", () => onChange(sel.value));
    wrap.append(lbl, sel);
    return wrap;
  }

  function typeField(labelText, inputType, value, onChange, placeholder) {
    const wrap = document.createElement("div");
    wrap.className = "type-field";
    const lbl = document.createElement("label"); lbl.textContent = labelText;
    const inp = document.createElement("input");
    inp.type = inputType; inp.value = value; inp.placeholder = placeholder;
    inp.addEventListener("pointerdown", e => e.stopPropagation());
    inp.addEventListener("input", () => onChange(inp.value));
    if (inputType === "number") { inp.min = 1; inp.max = 3600; }
    wrap.append(lbl, inp);
    return wrap;
  }

  function buildImage(win, ctx) {
    const box = document.createElement("div");
    box.className = "win-image";
    if (win.image) {
      const img = document.createElement("img"); img.src = win.image; img.alt = "";
      const acts = document.createElement("div"); acts.className = "img-actions";
      acts.append(
        miniBtn("Заменить", () => pickImage(win, ctx)),
        miniBtn("Ссылкой",  () => setImageByUrl(win, ctx)),
        miniBtn("Убрать",   () => { ctx.state.updateWindow(win.id, {image:null}); ctx.rerender(); })
      );
      box.append(img, acts);
    } else {
      const ph = document.createElement("div");
      ph.className = "img-placeholder"; ph.textContent = "🖼 Добавить картинку";
      ph.addEventListener("pointerdown", e => e.stopPropagation());
      ph.addEventListener("click", () => pickImage(win, ctx));
      const acts = document.createElement("div"); acts.className = "img-actions";
      acts.appendChild(miniBtn("или вставить ссылку", () => setImageByUrl(win, ctx)));
      box.append(ph, acts);
    }
    return box;
  }

  function miniBtn(text, onClick) {
    const b = document.createElement("button"); b.className = "mini-btn"; b.textContent = text;
    b.addEventListener("pointerdown", e => e.stopPropagation());
    b.addEventListener("click", onClick);
    return b;
  }

  function pickImage(win, ctx) {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = "image/*";
    inp.addEventListener("change", () => {
      const file = inp.files && inp.files[0]; if (!file) return;
      const r = new FileReader();
      r.onload = () => { ctx.state.updateWindow(win.id, {image: r.result}); ctx.rerender(); };
      r.readAsDataURL(file);
    });
    inp.click();
  }

  function setImageByUrl(win, ctx) {
    const url = prompt("Ссылка на картинку:", win.image || "");
    if (url !== null) { ctx.state.updateWindow(win.id, {image: url.trim()||null}); ctx.rerender(); }
  }

  function buildText(win, ctx) {
    const lbl = document.createElement("div"); lbl.className = "section-label"; lbl.textContent = "Текст сообщения";
    const text = document.createElement("div");
    text.className = "win-text"; text.contentEditable = "true"; text.textContent = win.text;
    text.addEventListener("pointerdown", e => e.stopPropagation());
    text.addEventListener("input", () => ctx.state.updateWindow(win.id, {text: text.innerText}));
    const wrap = document.createElement("div"); wrap.append(lbl, text);
    return wrap;
  }

  function buildNote(win, ctx) {
    const wrap = document.createElement("div");
    wrap.className = "win-note-wrap";

    const toggle = document.createElement("button");
    toggle.className = "note-toggle" + (win.note ? " has-note" : "");
    toggle.textContent = win.note ? "📝 Заметка ✓" : "📝 Заметка";

    const ta = document.createElement("textarea");
    ta.className = "win-note";
    ta.placeholder = "Поясните что происходит в этом блоке: контекст, логика, переменные…";
    ta.value = win.note || "";
    ta.style.display = win.note ? "block" : "none";

    toggle.addEventListener("pointerdown", e => e.stopPropagation());
    toggle.addEventListener("click", () => {
      const open = ta.style.display !== "none";
      ta.style.display = open ? "none" : "block";
      if (!open) { ta.focus(); ta.style.height = "auto"; }
    });

    ta.addEventListener("pointerdown", e => e.stopPropagation());
    ta.addEventListener("input", () => {
      ctx.state.updateWindow(win.id, { note: ta.value });
      toggle.textContent = ta.value ? "📝 Заметка ✓" : "📝 Заметка";
      toggle.classList.toggle("has-note", !!ta.value);
    });

    wrap.append(toggle, ta);
    return wrap;
  }

  function enableWindowDrag(win, el, handle, ctx) {
    // Drag works from the whole block, not just the header
    el.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      const t = e.target;
      // Skip interactive elements
      if (t.isContentEditable) return;
      if (["INPUT","TEXTAREA","SELECT","BUTTON","A"].includes(t.tagName)) return;
      if (t.closest(".connector,.btn-actions,.win-del,.btn-settings,.img-actions,.img-placeholder,.add-btn,.note-toggle,.mini-btn")) return;

      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      el.classList.add("dragging");
      const start = BK.screenToWorld(e.clientX, e.clientY);
      const offX = start.x - win.x, offY = start.y - win.y;

      function move(ev) {
        const p = BK.screenToWorld(ev.clientX, ev.clientY);
        win.x = Math.round(p.x - offX); win.y = Math.round(p.y - offY);
        el.style.left = win.x + "px"; el.style.top = win.y + "px";
        ctx.redrawLinks();
      }
      function up() {
        el.releasePointerCapture(e.pointerId);
        el.classList.remove("dragging");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        ctx.state.saveLocal();
      }
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
  }

  Object.assign(BK, { renderWindow });
})(window.BK);
