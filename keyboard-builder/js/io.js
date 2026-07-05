window.BK = window.BK || {};
(function (BK) {
  function downloadProject() {
    const src = BK.getState();
    // title — только для редактора, в файл не идёт
    const exported = {
      version: src.version,
      windows: src.windows.map(({ title, ...rest }) => rest),
    };
    const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "bot-logic.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function openProject(file, onLoaded) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result);
        if (parsed && Array.isArray(parsed.windows)) {
          // restore missing title field for editor
          parsed.windows.forEach((w, i) => { if (!w.title) w.title = `Блок ${i + 1}`; });
          BK.replaceState(parsed);
          if (onLoaded) onLoaded();
        } else {
          alert("Файл не похож на проект бота.");
        }
      } catch (e) { alert("Не удалось прочитать файл — не корректный JSON."); }
    };
    reader.readAsText(file);
  }

  // ── Share via URL hash ───────────────────────────────────────────────────
  function shareProject() {
    const btn = document.getElementById("btn-share");
    try {
      const json = JSON.stringify(BK.getState());
      const b64 = btoa(unescape(encodeURIComponent(json)));
      const url = location.href.split("#")[0] + "#share=" + b64;
      _copyText(url);
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = "✓ Ссылка скопирована!";
        setTimeout(() => { btn.textContent = orig; }, 2500);
      }
    } catch (e) {
      alert("Не удалось создать ссылку — возможно, проект слишком большой.");
    }
  }

  function _copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(() => _copyFallback(text));
    } else {
      _copyFallback(text);
    }
  }

  function _copyFallback(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;top:-9999px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { prompt("Скопируйте ссылку:", text); }
    document.body.removeChild(ta);
  }

  function loadFromHash() {
    const hash = location.hash;
    if (!hash.startsWith("#share=")) return false;
    try {
      const json = decodeURIComponent(escape(atob(hash.slice(7))));
      const parsed = JSON.parse(json);
      parsed.windows.forEach((w, i) => { if (!w.title) w.title = `Блок ${i + 1}`; });
      BK.replaceState(parsed);
      return true;
    } catch (e) { return false; }
  }

  Object.assign(BK, { downloadProject, openProject, shareProject, loadFromHash });
})(window.BK);
