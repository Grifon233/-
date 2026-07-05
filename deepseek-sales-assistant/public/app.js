const state = {
  agents: [],
  salesCases: [],
  activeAgentId: null,
  activeCaseId: null,
  histories: JSON.parse(localStorage.getItem("deepseek-sales-histories-v2") || "{}"),
  isSending: false
};

const elements = {
  agentList: document.querySelector("#agentList"),
  caseTabs: document.querySelector("#caseTabs"),
  agentAvatar: document.querySelector("#agentAvatar"),
  agentName: document.querySelector("#agentName"),
  agentTagline: document.querySelector("#agentTagline"),
  repoLink: document.querySelector("#repoLink"),
  resetButton: document.querySelector("#resetButton"),
  statusStrip: document.querySelector("#statusStrip"),
  statusText: document.querySelector("#statusText"),
  modelLabel: document.querySelector("#modelLabel"),
  caseSummary: document.querySelector("#caseSummary"),
  caseProof: document.querySelector("#caseProof"),
  productList: document.querySelector("#productList"),
  repoStars: document.querySelector("#repoStars"),
  repoLanguage: document.querySelector("#repoLanguage"),
  repoLicense: document.querySelector("#repoLicense"),
  repoSummary: document.querySelector("#repoSummary"),
  strengthList: document.querySelector("#strengthList"),
  stageList: document.querySelector("#stageList"),
  messageList: document.querySelector("#messageList"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  quickPrompts: document.querySelector("#quickPrompts")
};

function activeAgent() {
  return state.agents.find((agent) => agent.id === state.activeAgentId);
}

function activeCase() {
  return state.salesCases.find((salesCase) => salesCase.id === state.activeCaseId);
}

function historyKey(agent, salesCase) {
  return `${agent.id}:${salesCase.id}`;
}

function saveHistories() {
  localStorage.setItem("deepseek-sales-histories-v2", JSON.stringify(state.histories));
}

function openingMessage(agent, salesCase) {
  return `Добрый день, это ${agent.salespersonName}, ${salesCase.companyName}. Помогаю подобрать ${salesCase.offerName} без лишней переплаты и с нормальной проверкой под задачу. Чтобы не называть цену в воздух, уточню: ${salesCase.discoveryQuestion}`;
}

function getHistory(agent, salesCase) {
  const key = historyKey(agent, salesCase);
  if (!state.histories[key]) {
    state.histories[key] = [
      {
        role: "assistant",
        content: openingMessage(agent, salesCase),
        toolLog: []
      }
    ];
  }

  return state.histories[key];
}

function renderIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function setStatus(type, text) {
  elements.statusStrip.classList.remove("is-ready", "is-error");
  if (type) {
    elements.statusStrip.classList.add(type);
  }
  elements.statusText.textContent = text;
}

function renderAgents() {
  elements.agentList.innerHTML = state.agents
    .map(
      (agent) => `
        <button class="agent-button ${agent.id === state.activeAgentId ? "is-active" : ""}" data-agent-id="${agent.id}">
          <i data-lucide="${agent.buttonIcon}"></i>
          <span>
            <strong>${agent.name}</strong>
            <span>${agent.tagline}</span>
          </span>
          <span class="agent-stars">${agent.stars.toLocaleString("ru-RU")} ★</span>
        </button>
      `
    )
    .join("");

  renderIcons();
}

function renderCaseTabs() {
  elements.caseTabs.innerHTML = state.salesCases
    .map(
      (salesCase) => `
        <button class="case-tab ${salesCase.id === state.activeCaseId ? "is-active" : ""}" data-case-id="${salesCase.id}">
          <i data-lucide="${salesCase.icon}"></i>
          <span>${salesCase.label}</span>
        </button>
      `
    )
    .join("");

  renderIcons();
}

function renderInspector(agent, salesCase) {
  elements.agentAvatar.textContent = agent.avatar;
  elements.agentName.textContent = agent.name;
  elements.agentTagline.textContent = agent.tagline;
  elements.repoLink.href = agent.repo;
  elements.caseSummary.textContent = `${salesCase.companyName}: ${salesCase.summary}`;
  elements.caseProof.textContent = `${salesCase.proof} ${salesCase.delivery}`;
  elements.repoStars.textContent = agent.stars.toLocaleString("ru-RU");
  elements.repoLanguage.textContent = agent.language;
  elements.repoLicense.textContent = agent.license;
  elements.repoSummary.textContent = agent.repoSummary;

  elements.productList.innerHTML = salesCase.products
    .map(
      (product) => `
        <div class="product-item">
          <strong>${product.name}</strong>
          <span>${product.price}</span>
          <span>${product.fit}</span>
          <span>${product.details}</span>
        </div>
      `
    )
    .join("");

  elements.strengthList.innerHTML = agent.strengths
    .map((strength) => `<span class="pill">${strength}</span>`)
    .join("");

  elements.stageList.innerHTML = agent.stageModel
    .map((stage) => `<li>${stage.replace(/^\d+\.\s*/, "")}</li>`)
    .join("");
}

function renderMessages(agent, salesCase) {
  const history = getHistory(agent, salesCase);
  elements.messageList.innerHTML = history
    .map((message) => {
      const isUser = message.role === "user";
      const toolLog = message.toolLog?.length
        ? `<div class="tool-log">${message.toolLog
            .map((tool) => `<span class="tool-chip">${tool.name}</span>`)
            .join("")}</div>`
        : "";

      return `
        <article class="message ${isUser ? "is-user" : "is-assistant"}">
          <div class="message-meta">${isUser ? "Клиент" : `${agent.name} / ${salesCase.label}`}</div>
          <div class="message-bubble">${escapeHtml(message.content)}</div>
          ${toolLog}
        </article>
      `;
    })
    .join("");

  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function renderPending() {
  const agent = activeAgent();
  const salesCase = activeCase();
  const pending = document.createElement("article");
  pending.className = "message is-assistant is-pending";
  pending.innerHTML = `
    <div class="message-meta">${agent.name} / ${salesCase.label}</div>
    <div class="message-bubble">Думаю над ответом и подбираю лучший следующий шаг...</div>
  `;
  elements.messageList.appendChild(pending);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderCurrentView() {
  const agent = activeAgent();
  const salesCase = activeCase();
  if (!agent || !salesCase) {
    return;
  }

  getHistory(agent, salesCase);
  renderAgents();
  renderCaseTabs();
  renderInspector(agent, salesCase);
  renderMessages(agent, salesCase);
  saveHistories();
}

function selectAgent(agentId) {
  state.activeAgentId = agentId;
  renderCurrentView();
}

function selectCase(caseId) {
  state.activeCaseId = caseId;
  renderCurrentView();
}

function setSending(isSending) {
  state.isSending = isSending;
  elements.messageInput.disabled = isSending;
  elements.chatForm.querySelector("button").disabled = isSending;
  elements.quickPrompts.querySelectorAll("button").forEach((button) => {
    button.disabled = isSending;
  });
  elements.caseTabs.querySelectorAll("button").forEach((button) => {
    button.disabled = isSending;
  });
}

async function sendMessage(text) {
  const agent = activeAgent();
  const salesCase = activeCase();
  const content = text.trim();
  if (!agent || !salesCase || !content || state.isSending) {
    return;
  }

  const history = getHistory(agent, salesCase);
  history.push({ role: "user", content });
  saveHistories();
  renderMessages(agent, salesCase);
  renderPending();
  setSending(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agentId: agent.id,
        caseId: salesCase.id,
        messages: history.map(({ role, content }) => ({ role, content }))
      })
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Ошибка ответа сервера");
    }

    history.push({
      role: "assistant",
      content: payload.content,
      toolLog: payload.toolLog || []
    });
    saveHistories();
    renderMessages(agent, salesCase);
  } catch (error) {
    history.push({
      role: "assistant",
      content: `Сейчас не могу достучаться до модели: ${error.message}. Проверьте ключ и повторим заход?`,
      toolLog: []
    });
    saveHistories();
    renderMessages(agent, salesCase);
    setStatus("is-error", "Ошибка DeepSeek API или локального сервера");
  } finally {
    setSending(false);
    elements.messageInput.focus();
  }
}

async function loadData() {
  const [agentsResponse, healthResponse] = await Promise.all([
    fetch("/api/agents"),
    fetch("/api/health")
  ]);
  const agentsPayload = await agentsResponse.json();
  const healthPayload = await healthResponse.json();

  state.agents = agentsPayload.agents;
  state.salesCases = agentsPayload.salesCases;
  state.activeAgentId = state.agents[0]?.id;
  state.activeCaseId = state.salesCases[0]?.id;
  elements.modelLabel.textContent = healthPayload.model;

  if (healthPayload.hasApiKey) {
    setStatus("is-ready", `DeepSeek подключен: ${healthPayload.model}`);
  } else {
    setStatus("is-error", "Нет DEEPSEEK_API_KEY: добавьте .env или secrets.json");
  }

  renderCurrentView();
}

elements.agentList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-agent-id]");
  if (!button) {
    return;
  }
  selectAgent(button.dataset.agentId);
});

elements.caseTabs.addEventListener("click", (event) => {
  const button = event.target.closest("[data-case-id]");
  if (!button) {
    return;
  }
  selectCase(button.dataset.caseId);
});

elements.resetButton.addEventListener("click", () => {
  const agent = activeAgent();
  const salesCase = activeCase();
  if (!agent || !salesCase) {
    return;
  }

  state.histories[historyKey(agent, salesCase)] = [
    { role: "assistant", content: openingMessage(agent, salesCase), toolLog: [] }
  ];
  saveHistories();
  renderMessages(agent, salesCase);
});

elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.messageInput.value;
  elements.messageInput.value = "";
  sendMessage(text);
});

elements.quickPrompts.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-text]");
  if (!button) {
    return;
  }
  sendMessage(button.dataset.text);
});

elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});

loadData().catch((error) => {
  setStatus("is-error", `Не удалось загрузить панель: ${error.message}`);
});
