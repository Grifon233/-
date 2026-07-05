window.BK = window.BK || {};
(function (BK) {
  let panX = 0, panY = 0, scale = 1;
  const MIN_SCALE = 0.3, MAX_SCALE = 2.5, GRID_BASE = 28;
  let worldEl = null, canvasEl = null;

  function initCanvas(world, canvas) {
    worldEl = world; canvasEl = canvas;
    applyTransform();
    canvasEl.addEventListener("pointerdown", onPointerDown);
    canvasEl.addEventListener("wheel", onWheel, { passive: false });
  }

  function applyTransform() {
    worldEl.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
    const size = GRID_BASE * scale;
    const ox = ((panX % size) + size) % size;
    const oy = ((panY % size) + size) % size;
    canvasEl.style.setProperty("--grid-size", `${size}px`);
    canvasEl.style.setProperty("--grid-x", `${ox}px`);
    canvasEl.style.setProperty("--grid-y", `${oy}px`);
  }

  let panning = false, startX = 0, startY = 0, startPanX = 0, startPanY = 0;

  function isBackground(target) {
    return !target.closest(".window") && !target.closest(".connector");
  }

  function onPointerDown(e) {
    if (e.button !== 0 || window.__draggingLink || !isBackground(e.target)) return;
    panning = true;
    startX = e.clientX; startY = e.clientY;
    startPanX = panX; startPanY = panY;
    canvasEl.classList.add("panning");
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }
  function onPointerMove(e) {
    if (!panning) return;
    panX = startPanX + (e.clientX - startX);
    panY = startPanY + (e.clientY - startY);
    applyTransform();
  }
  function onPointerUp() {
    panning = false;
    canvasEl.classList.remove("panning");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
  }

  function onWheel(e) {
    e.preventDefault();
    const rect = canvasEl.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const wx = (mx - panX) / scale, wy = (my - panY) / scale;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const ns = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * factor));
    panX = mx - wx * ns; panY = my - wy * ns; scale = ns;
    applyTransform();
  }

  function screenToWorld(cx, cy) {
    const r = canvasEl.getBoundingClientRect();
    return { x: (cx - r.left - panX) / scale, y: (cy - r.top - panY) / scale };
  }
  function getScale() { return scale; }
  function centerWorldPoint() {
    const r = canvasEl.getBoundingClientRect();
    return screenToWorld(r.left + r.width / 2, r.top + r.height / 2);
  }

  Object.assign(BK, { initCanvas, screenToWorld, getScale, centerWorldPoint });
})(window.BK);
