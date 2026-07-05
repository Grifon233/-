window.BK = window.BK || {};
(function (BK) {
  const canvas = document.getElementById("canvas");
  const world  = document.getElementById("world");

  const ctx = {
    state:       BK,
    rerender:    renderAll,
    redrawLinks: redrawLinks,
  };

  function redrawLinks() {
    // clear connected state before redraw
    document.querySelectorAll(".connector").forEach(c => c.classList.remove("connected"));
    BK.renderLinks(BK.getState(), onDeleteLink);
  }

  function onDeleteLink(winId, btnId) {
    BK.updateButton(winId, btnId, { target: null });
    renderAll();
  }

  function renderAll() {
    [...world.querySelectorAll(".window")].forEach(el => el.remove());
    BK.getState().windows.forEach(win => world.appendChild(BK.renderWindow(win, ctx)));
    redrawLinks();
  }

  function init() {
    BK.loadLocal();

    // If opened via share link — load encoded state and enter view mode
    const isShared = BK.loadFromHash();
    if (isShared) {
      ["btn-open", "btn-download", "btn-help", "divider-io", "divider-help"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = "none";
      });
    }

    BK.initCanvas(world, canvas);

    // create buttons for each type
    document.querySelectorAll(".create-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const c = BK.centerWorldPoint();
        BK.addWindow(Math.round(c.x - 140), Math.round(c.y - 100), btn.dataset.type);
        renderAll();
      });
    });

    document.getElementById("btn-download").addEventListener("click", BK.downloadProject);
    document.getElementById("btn-share").addEventListener("click", BK.shareProject);
    document.getElementById("btn-help").addEventListener("click", () => BK.openHelp(renderAll));

    const fileInput = document.getElementById("file-input");
    document.getElementById("btn-open").addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", e => {
      const file = e.target.files && e.target.files[0];
      if (file) BK.openProject(file, renderAll);
      fileInput.value = "";
    });

    renderAll();
  }

  init();
})(window.BK);
