const state = {
  leads: [],
  stats: null,
  initialized: false,
  maxSeenId: Number(localStorage.getItem("leadMonitorMaxSeenId") || "0"),
  aiReplies: {},
  lastHiddenLead: null,
  expandedLeadIds: new Set(),
};

const sourceLabels = {
  kwork: "Kwork",
  fl_ru: "FL.ru",
  freelance_ru: "Freelance.ru",
};

const sourceClasses = {
  kwork: "source-kwork",
  fl_ru: "source-fl_ru",
  freelance_ru: "source-freelance_ru",
};

const actionLabels = {
  hide: "Скрыто крестиком",
  read: "Отмечено галочкой",
  unread: "Вернул в непрочитанные",
  restore: "Вернул в ленту",
  closed: "Закрыто площадкой",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function activeSources() {
  return $$(".check-row input[type='checkbox'][value]:checked").map((item) => item.value);
}

function currentQuery() {
  return $("#searchInput").value.trim().toLowerCase();
}

function filteredLeads() {
  const sources = new Set(activeSources());
  const query = currentQuery();
  const unreadOnly = $("#unreadOnly").checked;

  return state.leads.filter((lead) => {
    if (!sources.has(lead.source)) return false;
    if (unreadOnly && lead.is_read) return false;
    if (!query) return true;
    const haystack = `${lead.title} ${lead.description} ${lead.category}`.toLowerCase();
    return haystack.includes(query);
  });
}

function renderStats() {
  const stats = state.stats || {};
  $("#totalCount").textContent = stats.total || 0;
  $("#unreadCount").textContent = stats.unread || 0;
  $("#actionCount").textContent = stats.actions || 0;

  const scanner = stats.scanner || {};
  const lastScan = stats.last_scan || {};
  const dot = $("#scanDot");
  dot.classList.toggle("running", Boolean(scanner.running));
  $("#scanStatus").textContent = scanner.running
    ? "Идет проверка сайтов"
    : "Мониторинг активен";
  $("#lastScan").textContent = lastScan.finished_at ? formatDate(lastScan.finished_at) : "-";
  $("#nextScan").textContent = scanner.next_scan_at ? formatDate(scanner.next_scan_at) : "-";

  const counters = stats.by_source || {};
  $("#sourceCounters").innerHTML = Object.entries(sourceLabels)
    .map(([key, label]) => `<span class="counter-pill">${label}: ${counters[key] || 0}</span>`)
    .join("");
}

function renderLeads() {
  const list = $("#leadList");
  const leads = filteredLeads();

  if (!leads.length) {
    list.innerHTML = `<div class="empty">Пока нет заявок под выбранные фильтры</div>`;
    return;
  }

  list.innerHTML = leads
    .map((lead) => {
      const keywords = (lead.matched_keywords || [])
        .slice(0, 8)
        .map((word) => `<span class="keyword">${escapeHtml(word)}</span>`)
        .join("");
      const sourceClass = sourceClasses[lead.source] || "";
      const date = lead.published_at || lead.raw_published || lead.first_seen_at;
      const description = escapeHtml(lead.description || "Описание не найдено в ленте площадки.");
      const externalLabel = `Открыть ${sourceLabels[lead.source] || "площадку"}`;
      const aiReply = state.aiReplies[lead.id];
      const hasSourcePreview = /(\.\.\.|…)$/u.test((lead.description || "").trim());
      const isExpanded = state.expandedLeadIds.has(lead.id);
      return `
        <article class="lead-card ${lead.is_read ? "read" : ""} ${isExpanded ? "expanded" : ""}" data-id="${lead.id}">
          <div class="lead-main">
            <div class="meta-row">
              <span class="source-badge">
                <span class="source-dot ${sourceClass}"></span>
                ${sourceLabels[lead.source] || escapeHtml(lead.source)}
              </span>
              <span>${formatDate(date)}</span>
              ${lead.budget ? `<span>${escapeHtml(lead.budget)}</span>` : ""}
              ${lead.category ? `<span>${escapeHtml(lead.category)}</span>` : ""}
              <span>score ${lead.score}</span>
            </div>
            <button class="lead-title expand-description" type="button">
              ${escapeHtml(lead.title)}
            </button>
            <div class="lead-desc">
              <div class="desc-text">${description}</div>
              ${
                hasSourcePreview
                  ? `<div class="desc-preview-note">Площадка отдала укороченное описание. Если задача еще доступна, полная версия откроется по кнопке внешней ссылки.</div>`
                  : ""
              }
              <button class="toggle-description" type="button">
                <span class="toggle-label">${isExpanded ? "Свернуть" : "Показать полностью"}</span>
                <i data-lucide="${isExpanded ? "chevron-up" : "chevron-down"}"></i>
              </button>
            </div>
            ${renderAiReplyPanel(aiReply)}
            <div class="keyword-row">${keywords}</div>
          </div>
          <div class="card-actions">
            <a class="card-button external-link" href="${escapeHtml(lead.url)}" target="_blank" rel="noreferrer" title="${externalLabel}">
              <i data-lucide="external-link"></i>
            </a>
            <button class="card-button ai-reply-button" title="Создать ИИ-отклик">
              <i data-lucide="${aiReply?.loading ? "loader-circle" : "sparkles"}"></i>
            </button>
            <button class="card-button read-toggle" title="${lead.is_read ? "Вернуть в непрочитанные" : "Отметить прочитанным"}">
              <i data-lucide="${lead.is_read ? "mail" : "check"}"></i>
            </button>
            <button class="card-button hide-lead" title="Скрыть">
              <i data-lucide="x"></i>
            </button>
          </div>
        </article>
      `;
    })
    .join("");

  if (window.lucide) {
    window.lucide.createIcons();
  }
  scheduleDescriptionToggleUpdate();
}

function renderAiReplyPanel(aiReply) {
  if (!aiReply) return "";

  const meta = aiReply.model
    ? `<div class="ai-meta">${escapeHtml(aiReply.provider || "ИИ")} · ${escapeHtml(aiReply.model)}</div>`
    : "";
  const body = aiReply.loading
    ? `<div class="ai-loading"><i data-lucide="loader-circle"></i><span>Формирую отклик под эту задачу...</span></div>`
    : aiReply.error
      ? `<div class="ai-error">${escapeHtml(aiReply.error)}</div>`
      : `<div class="ai-text">${escapeHtml(aiReply.reply)}</div>`;

  return `
    <section class="ai-panel">
      <div class="ai-head">
        <span><i data-lucide="sparkles"></i> ИИ-отклик</span>
        ${meta}
      </div>
      ${body}
    </section>
  `;
}

async function loadStats() {
  const response = await fetch("/api/stats");
  state.stats = await response.json();
  renderStats();
}

async function loadLeads() {
  const response = await fetch("/api/leads");
  const payload = await response.json();
  state.leads = payload.items || [];
  notifyAboutNewLeads(state.leads);
  renderLeads();
}

function notifyAboutNewLeads(leads) {
  const maxId = leads.reduce((max, lead) => Math.max(max, lead.id), state.maxSeenId);
  const newLeads = leads.filter((lead) => lead.id > state.maxSeenId && !lead.is_read);

  if (!state.initialized) {
    state.maxSeenId = maxId;
    localStorage.setItem("leadMonitorMaxSeenId", String(maxId));
    state.initialized = true;
    return;
  }

  if (newLeads.length && Notification.permission === "granted") {
    const topLead = newLeads[0];
    new Notification(`Новые заявки: ${newLeads.length}`, {
      body: `${sourceLabels[topLead.source] || topLead.source}: ${topLead.title}`,
    });
  }

  if (maxId > state.maxSeenId) {
    state.maxSeenId = maxId;
    localStorage.setItem("leadMonitorMaxSeenId", String(maxId));
  }
}

async function refresh() {
  await Promise.all([loadStats(), loadLeads()]);
}

async function scanNow() {
  $("#scanButton").disabled = true;
  try {
    await fetch("/api/scan", { method: "POST" });
    await loadStats();
  } finally {
    setTimeout(() => {
      $("#scanButton").disabled = false;
    }, 1200);
  }
}

async function markRead(id, isRead) {
  await fetch(`/api/leads/${id}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_read: isRead }),
  });
  await refresh();
}

async function hideLead(id) {
  const lead = state.leads.find((item) => item.id === id);
  await fetch(`/api/leads/${id}/hide`, { method: "POST" });
  state.lastHiddenLead = lead || null;
  showUndoHidden(lead);
  await refresh();
}

async function restoreLead(id) {
  await fetch(`/api/leads/${id}/restore`, { method: "POST" });
  state.lastHiddenLead = null;
  await refresh();
}

function showUndoHidden(lead) {
  if (!lead) return;
  const existing = $(".toast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `
    <span>Скрыто: ${escapeHtml(lead.title)}</span>
    <button type="button" class="toast-undo">Вернуть</button>
  `;
  document.body.appendChild(toast);
  toast.querySelector(".toast-undo").addEventListener("click", async () => {
    await restoreLead(lead.id);
    toast.remove();
  });
  setTimeout(() => toast.remove(), 12000);
}

function renderActionLeads(items) {
  const list = $("#actionList");
  if (!items.length) {
    list.innerHTML = `<div class="empty small-empty">Пока нет действий по карточкам</div>`;
    return;
  }

  list.innerHTML = items
    .map((lead) => {
      const date = lead.last_action_at || lead.hidden_at || lead.last_seen_at;
      const actionLabel = actionLabels[lead.last_action] || "Действие";
      const canRestore = Boolean(lead.is_hidden);
      const canUnread = Boolean(lead.is_read) && !lead.is_hidden;
      return `
        <article class="hidden-item" data-id="${lead.id}">
          <div>
            <div class="hidden-title">${escapeHtml(lead.title)}</div>
            <div class="hidden-meta">
              <span class="action-pill action-${escapeHtml(lead.last_action)}">${escapeHtml(actionLabel)}</span>
              ${sourceLabels[lead.source] || escapeHtml(lead.source)}
              · ${formatDate(date)}
              ${lead.budget ? ` · ${escapeHtml(lead.budget)}` : ""}
            </div>
            <div class="hidden-desc">${escapeHtml(lead.description || "").slice(0, 260)}</div>
          </div>
          <div class="hidden-actions">
            <a class="card-button external-link" href="${escapeHtml(lead.url)}" target="_blank" rel="noreferrer" title="Открыть в браузере">
              <i data-lucide="external-link"></i>
            </a>
            ${
              canRestore
                ? `<button class="card-button restore-lead" title="Вернуть в ленту"><i data-lucide="rotate-ccw"></i></button>`
                : ""
            }
            ${
              canUnread
                ? `<button class="card-button unread-lead" title="Вернуть в непрочитанные"><i data-lucide="mail"></i></button>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

async function openActionLogModal() {
  $("#actionModal").hidden = false;
  $("#actionList").innerHTML = `<div class="empty small-empty">Загружаю журнал...</div>`;
  const response = await fetch("/api/leads/actions");
  const payload = await response.json();
  renderActionLeads(payload.items || []);
}

function closeActionLogModal() {
  $("#actionModal").hidden = true;
}

async function generateAiReply(id) {
  state.aiReplies[id] = { loading: true };
  renderLeads();

  try {
    const response = await fetch(`/api/leads/${id}/ai-reply`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "ИИ не вернул отклик");
    }
    state.aiReplies[id] = {
      loading: false,
      reply: payload.reply,
      provider: payload.provider,
      model: payload.model,
    };
  } catch (error) {
    state.aiReplies[id] = {
      loading: false,
      error: error.message || "Не удалось создать отклик",
    };
  }

  renderLeads();
}

function toggleCardDescription(card) {
  if (!card.classList.contains("expandable")) return;
  const expanded = card.classList.toggle("expanded");
  const id = Number(card.dataset.id);
  if (expanded) {
    state.expandedLeadIds.add(id);
  } else {
    state.expandedLeadIds.delete(id);
  }
  const toggle = card.querySelector(".toggle-description");
  const label = toggle?.querySelector(".toggle-label");
  const icon = toggle?.querySelector("i");
  if (label) {
    label.textContent = expanded ? "Свернуть" : "Показать полностью";
  }
  if (icon) {
    icon.setAttribute("data-lucide", expanded ? "chevron-up" : "chevron-down");
  }
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function updateDescriptionToggles() {
  const collapsedHeight = 126;
  $$(".lead-card").forEach((card) => {
    const desc = card.querySelector(".desc-text");
    const toggle = card.querySelector(".toggle-description");
    if (!desc || !toggle) return;

    const canExpand = desc.scrollHeight > collapsedHeight + 2;
    card.classList.toggle("expandable", canExpand);
    toggle.hidden = !canExpand;
    toggle.setAttribute("aria-hidden", canExpand ? "false" : "true");

    if (!canExpand) {
      card.classList.remove("expanded");
      state.expandedLeadIds.delete(Number(card.dataset.id));
      const label = toggle.querySelector(".toggle-label");
      const icon = toggle.querySelector("i");
      if (label) label.textContent = "Показать полностью";
      if (icon) icon.setAttribute("data-lucide", "chevron-down");
    }
  });

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function scheduleDescriptionToggleUpdate() {
  requestAnimationFrame(updateDescriptionToggles);
  setTimeout(updateDescriptionToggles, 250);
}

function wireEvents() {
  $("#scanButton").addEventListener("click", scanNow);
  $("#readAllButton").addEventListener("click", async () => {
    await fetch("/api/leads/read-all", { method: "POST" });
    await refresh();
  });
  $("#actionLogButton").addEventListener("click", openActionLogModal);
  $("#closeActionLogButton").addEventListener("click", closeActionLogModal);
  $("#actionModal").addEventListener("click", async (event) => {
    if (event.target.id === "actionModal") {
      closeActionLogModal();
      return;
    }
    const restoreButton = event.target.closest(".restore-lead");
    const unreadButton = event.target.closest(".unread-lead");
    if (!restoreButton && !unreadButton) return;
    const item = event.target.closest(".hidden-item");
    if (!item) return;
    const id = Number(item.dataset.id);
    if (restoreButton) {
      await restoreLead(id);
    }
    if (unreadButton) {
      await markRead(id, false);
    }
    await openActionLogModal();
  });
  $("#notifyButton").addEventListener("click", async () => {
    if ("Notification" in window) {
      await Notification.requestPermission();
    }
  });
  $("#searchInput").addEventListener("input", renderLeads);
  $("#unreadOnly").addEventListener("change", renderLeads);
  $$(".check-row input[type='checkbox'][value]").forEach((item) => {
    item.addEventListener("change", renderLeads);
  });
  $("#leadList").addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    const card = event.target.closest(".lead-card");
    if (!card) return;
    const id = Number(card.dataset.id);
    const lead = state.leads.find((item) => item.id === id);
    if (!lead) return;
    if (!button) return;
    if (
      button.classList.contains("expand-description") ||
      button.classList.contains("toggle-description")
    ) {
      toggleCardDescription(card);
      return;
    }
    if (button.classList.contains("read-toggle")) {
      await markRead(id, !lead.is_read);
    }
    if (button.classList.contains("ai-reply-button")) {
      await generateAiReply(id);
    }
    if (button.classList.contains("hide-lead")) {
      await hideLead(id);
    }
  });
  $("#leadList").addEventListener("click", (event) => {
    const card = event.target.closest(".lead-card");
    if (!card || event.target.closest("button, a")) return;
    if (event.target.closest(".lead-desc")) {
      toggleCardDescription(card);
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  wireEvents();
  window.addEventListener("resize", scheduleDescriptionToggleUpdate);
  if (window.lucide) {
    window.lucide.createIcons();
  }
  await refresh();
  setInterval(refresh, 25000);
});
