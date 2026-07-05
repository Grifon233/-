window.BK = window.BK || {};
(function (BK) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  function layer() { return document.getElementById("links-layer"); }

  function anchorWorld(el, side) {
    const r = el.getBoundingClientRect();
    const cx = side === "right" ? r.right : side === "left" ? r.left : r.left + r.width / 2;
    return BK.screenToWorld(cx, r.top + r.height / 2);
  }

  function curvePath(a, b) {
    const dx = Math.max(60, Math.abs(b.x - a.x) * 0.45);
    return `M ${a.x} ${a.y} C ${a.x+dx} ${a.y}, ${b.x-dx} ${b.y}, ${b.x} ${b.y}`;
  }

  function renderLinks(state, onDeleteLink) {
    const g = layer();
    while (g.firstChild) g.removeChild(g.firstChild);
    state.windows.forEach(win => {
      win.buttons.forEach(btn => {
        if (btn.action !== "goto" || !btn.target) return;
        if (!state.windows.find(w => w.id === btn.target)) return;

        const fromEl = document.querySelector(`.connector[data-win="${win.id}"][data-btn="${btn.id}"]`);
        const toEl   = document.querySelector(`.window[data-win="${btn.target}"]`);
        if (!fromEl || !toEl) return;

        const a = anchorWorld(fromEl, "right");
        const b = anchorWorld(toEl, "left");
        const d = curvePath(a, b);

        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", d);
        path.setAttribute("class", "link");
        path.setAttribute("marker-end", "url(#arrow)");
        // Mark connector as connected
        fromEl.classList.add("connected");

        const hit = document.createElementNS(SVG_NS, "path");
        hit.setAttribute("d", d);
        hit.setAttribute("class", "link-hit");
        const ti = document.createElementNS(SVG_NS, "title");
        ti.textContent = "Клик — удалить стрелку";
        hit.appendChild(ti);
        hit.addEventListener("click", () => onDeleteLink(win.id, btn.id));

        g.appendChild(path);
        g.appendChild(hit);
      });
    });
  }

  function beginLinkDrag(winId, btnId, e, ctx) {
    e.stopPropagation(); e.preventDefault();
    window.__draggingLink = true;

    const g = layer();
    const start = anchorWorld(e.currentTarget, "right");
    const temp = document.createElementNS(SVG_NS, "path");
    temp.setAttribute("class", "link link-temp");
    temp.setAttribute("marker-end", "url(#arrow)");
    g.appendChild(temp);

    function move(ev) {
      const p = BK.screenToWorld(ev.clientX, ev.clientY);
      temp.setAttribute("d", curvePath(start, p));
    }
    function up(ev) {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.__draggingLink = false;
      temp.remove();
      const winEl = ev.target.closest && ev.target.closest(".window");
      if (winEl && winEl.dataset.win !== winId) {
        ctx.state.updateButton(winId, btnId, { action: "goto", target: winEl.dataset.win });
      }
      ctx.rerender();
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  Object.assign(BK, { renderLinks, beginLinkDrag });
})(window.BK);
