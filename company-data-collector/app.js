// Frontend Logic for LeadOrchester Mail Validator - Anti-Abuse Rate Limited version

document.addEventListener("DOMContentLoaded", () => {
    checkPortStatus();
    updateLimitDisplay();
    initProxyPoolControls();
    initWorkspaceLayout();
    initSingleEnricher();
});

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#096;");
}

function normalizeDomainInput(input) {
    let value = String(input || "").trim().toLowerCase().replace(/\\/g, "/");
    if (!value) return "";
    if (!/^https?:\/\//i.test(value)) {
        value = `https://${value}`;
    }

    try {
        const parsed = new URL(value);
        const hostname = parsed.hostname.replace(/^www\./, "");
        if (hostname === "localhost") return hostname;
        if (!/^(?=.{1,253}$)(?:[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?\.)+[\p{L}\p{N}](?:[\p{L}\p{N}-]{0,61}[\p{L}\p{N}])?$/u.test(hostname)) {
            return "";
        }
        return hostname;
    } catch (e) {
        return "";
    }
}

function parseDomainListInput(input) {
    const seen = new Set();
    return String(input || "")
        .split(/[\n,;]+/)
        .flatMap(part => part.trim().split(/\s+/))
        .map(item => item.trim())
        .filter(Boolean)
        .filter(item => {
            const key = normalizeDomainInput(item) || item.toLowerCase();
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
}

function csvCell(value) {
    return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function initWorkspaceLayout() {
    const split = document.querySelector(".split-container");
    const collapseBtn = document.getElementById("collapse-results-btn");
    if (!split || !collapseBtn) return;

    split.classList.add("results-collapsed");
    collapseBtn.addEventListener("click", () => {
        split.classList.remove("results-open");
        split.classList.add("results-collapsed");
    });
}

function openResultsWorkspace() {
    const split = document.querySelector(".split-container");
    if (!split) return;
    split.classList.add("results-open");
    split.classList.remove("results-collapsed");
}

function closeResultsWorkspace() {
    const split = document.querySelector(".split-container");
    if (!split) return;
    split.classList.remove("results-open");
    split.classList.add("results-collapsed");
}

let proxyRowCounter = 0;

function createProxyRow(values = {}) {
    const row = document.createElement("div");
    row.className = "proxy-row";
    row.dataset.proxyId = values.id || `proxy-${Date.now()}-${proxyRowCounter++}`;
    row.innerHTML = `
        <label class="proxy-input-field proxy-host-field">
            <span>Хост SOCKS5</span>
            <input type="text" class="proxy-host-input" placeholder="socks5.example.com" value="${escapeAttr(values.host || "")}">
        </label>
        <label class="proxy-input-field">
            <span>Порт</span>
            <input type="number" class="proxy-port-input" placeholder="1080" min="1" max="65535" value="${escapeAttr(values.port || "")}">
        </label>
        <label class="proxy-input-field">
            <span>Логин</span>
            <input type="text" class="proxy-login-input" placeholder="login" value="${escapeAttr(values.username || "")}">
        </label>
        <label class="proxy-input-field">
            <span>Пароль</span>
            <input type="password" class="proxy-password-input" placeholder="password" value="${escapeAttr(values.password || "")}">
        </label>
        <label class="proxy-input-field">
            <span>Лимит</span>
            <input type="number" class="proxy-limit-input" placeholder="100" min="1" max="10000" value="${escapeAttr(values.limit || 100)}">
        </label>
        <button type="button" class="icon-btn proxy-remove-btn" title="Удалить строку">×</button>
    `;

    row.querySelectorAll("input").forEach(input => {
        input.addEventListener("input", updateProxyTotalLimit);
    });
    row.querySelector(".proxy-remove-btn").addEventListener("click", () => {
        row.remove();
        updateProxyTotalLimit();
    });

    return row;
}

function getProxyPoolConfig() {
    const enabled = document.getElementById("proxy-pool-enabled")?.checked || false;
    const rows = Array.from(document.querySelectorAll("#proxy-pool-rows .proxy-row"));
    return {
        enabled,
        proxies: rows.map(row => ({
            id: row.dataset.proxyId,
            type: "socks5",
            host: row.querySelector(".proxy-host-input").value.trim(),
            port: row.querySelector(".proxy-port-input").value.trim(),
            username: row.querySelector(".proxy-login-input").value.trim(),
            password: row.querySelector(".proxy-password-input").value,
            limit: row.querySelector(".proxy-limit-input").value.trim()
        })).filter(proxy => proxy.host || proxy.port || proxy.username || proxy.password)
    };
}

function updateProxyTotalLimit() {
    const totalEl = document.getElementById("proxy-total-limit");
    if (!totalEl) return;

    const proxyPool = getProxyPoolConfig();
    const total = proxyPool.proxies.reduce((sum, proxy) => {
        const limit = Number.parseInt(proxy.limit, 10);
        return sum + (Number.isInteger(limit) && limit > 0 ? limit : 0);
    }, 0);
    totalEl.textContent = `${total} проверок`;
}

function renderProxyPoolStatus(proxyStatus) {
    const resultEl = document.getElementById("proxy-test-result");
    if (!resultEl || !proxyStatus) return;

    const rows = proxyStatus.proxies.map(proxy => (
        `${escapeHtml(proxy.summary)}: ${proxy.used} / ${proxy.limit}, осталось ${proxy.remaining}`
    ));
    resultEl.innerHTML = `<strong>Лимит пула:</strong> ${escapeHtml(proxyStatus.totalUsed)} / ${escapeHtml(proxyStatus.totalLimit)}<br>${rows.join("<br>")}`;
}

function normalizeSocialUrl(url) {
    try {
        const parsed = new URL(String(url || "").trim());
        parsed.hash = "";
        const host = parsed.hostname.replace(/^www\./i, "").toLowerCase();
        let path = parsed.pathname.replace(/\/+$/, "").toLowerCase();
        if (host === "youtu.be") {
            path = `/channel/${path.replace(/^\/+/, "")}`;
        }
        return `${host}${path}`;
    } catch (e) {
        return String(url || "").trim().replace(/\/+$/, "").toLowerCase();
    }
}

function getUniqueSocials(socials = []) {
    const seen = new Set();
    const unique = [];
    socials.forEach(item => {
        const key = `${item.platform || ""}:${normalizeSocialUrl(item.url)}`;
        if (seen.has(key)) return;
        seen.add(key);
        unique.push(item);
    });
    return unique;
}

function initProxyPoolControls() {
    const enabled = document.getElementById("proxy-pool-enabled");
    const body = document.getElementById("proxy-pool-body");
    const rows = document.getElementById("proxy-pool-rows");
    const addBtn = document.getElementById("add-proxy-row-btn");
    const testBtn = document.getElementById("test-proxy-pool-btn");
    const resultEl = document.getElementById("proxy-test-result");

    if (!enabled || !body || !rows || !addBtn || !testBtn) return;

    const ensureFirstRow = () => {
        if (rows.children.length === 0) {
            rows.appendChild(createProxyRow({ limit: 100 }));
        }
        updateProxyTotalLimit();
    };

    enabled.addEventListener("change", () => {
        body.style.display = enabled.checked ? "flex" : "none";
        if (enabled.checked) ensureFirstRow();
    });

    addBtn.addEventListener("click", () => {
        rows.appendChild(createProxyRow({ limit: 100 }));
        updateProxyTotalLimit();
    });

    testBtn.addEventListener("click", async () => {
        const proxyPool = getProxyPoolConfig();
        if (!proxyPool.enabled || proxyPool.proxies.length === 0) {
            resultEl.textContent = "Добавьте хотя бы один SOCKS5-прокси.";
            resultEl.style.color = "var(--warning)";
            return;
        }

        testBtn.disabled = true;
        testBtn.textContent = "Проверка...";
        resultEl.textContent = "Проверяем web-доступ и SMTP TCP :25...";
        resultEl.style.color = "var(--text-secondary)";

        try {
            const response = await fetch("/api/proxy-test", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ proxyPool })
            });
            const data = await readApiJson(response);
            if (!response.ok) throw new Error(data.error || "Ошибка проверки прокси");

            const lines = data.results.map(item => {
                const status = item.ok ? "OK" : "Проблема";
                const web = item.webFetchOk ? "web OK" : "web нет";
                const smtp = item.smtpPort25Open ? "SMTP :25 OK" : "SMTP :25 закрыт";
                return `${status}: ${escapeHtml(item.summary)} — ${web}, ${smtp}, лимит ${escapeHtml(item.limit)}`;
            });
            const limitLine = data.proxyStatus
                ? `<br><strong>Лимит пула:</strong> ${escapeHtml(data.proxyStatus.totalUsed)} / ${escapeHtml(data.proxyStatus.totalLimit)}`
                : "";
            resultEl.innerHTML = lines.join("<br>") + limitLine;
            resultEl.style.color = data.results.every(item => item.ok) ? "var(--success)" : "var(--warning)";
        } catch (err) {
            resultEl.textContent = err.message;
            resultEl.style.color = "var(--danger)";
        } finally {
            testBtn.disabled = false;
            testBtn.textContent = "Проверить пул";
        }
    });
}

// Check Server Port 25 SMTP Outgoing Status
async function checkPortStatus() {
    const banner = document.getElementById("port-status-banner");
    const warningBox = document.getElementById("port-warning-box");
    
    try {
        const response = await fetch("/api/port-status");
        if (!response.ok) throw new Error();
        const data = await readApiJson(response);
        
        banner.innerHTML = "";
        
        if (data.blocked) {
            banner.className = "system-status-badge port-status-blocked";
            banner.innerHTML = `<span class="pulse-dot"></span> SMTP проверка: Ограничена (порт 25 закрыт)`;
            warningBox.style.display = "block";
        } else {
            banner.className = "system-status-badge port-status-open";
            banner.innerHTML = `<span class="pulse-dot"></span> SMTP проверка: Активна`;
            warningBox.style.display = "none";
        }
    } catch (e) {
        banner.className = "system-status-badge port-status-blocked";
        banner.innerHTML = `<span class="pulse-dot"></span> Сервер недоступен`;
    }
}

// Fetch and render current user limit status
async function updateLimitDisplay() {
    try {
        const res = await fetch("/api/limit-status");
        if (!res.ok) return;
        const data = await readApiJson(res);
        renderLimits(data);
    } catch (e) {
        console.error("Error loading limits status:", e);
    }
}

function renderLimits(data) {
    const display = document.getElementById("limit-display");
    const statusText = document.getElementById("limit-status-text");
    const fillFirst = document.getElementById("fill-first-half");
    const fillSecond = document.getElementById("fill-second-half");
    
    const firstUsed = data.firstHalfUsed;
    const secondUsed = data.secondHalfUsed;
    const totalUsed = firstUsed + secondUsed;
    
    display.textContent = `${totalUsed} / 20`;
    
    // Fill first segment (max 10)
    const firstPercent = (firstUsed / 10) * 100;
    fillFirst.style.width = `${firstPercent}%`;
    
    // Fill second segment (max 10)
    const secondPercent = (secondUsed / 10) * 100;
    fillSecond.style.width = `${secondPercent}%`;
    
    const now = Date.now();
    if (data.proxyMode) {
        statusText.innerHTML = "<strong>Режим SOCKS5-пула:</strong> серверный IP-лимит не расходуется. Используется лимит выбранного прокси.";
        statusText.style.color = "var(--success)";
    } else if (data.blockedUntil && now < data.blockedUntil) {
        const timeLeftMs = data.blockedUntil - now;
        const timeLeftMin = Math.ceil(timeLeftMs / (60 * 1000));
        statusText.innerHTML = `⚠️ <strong>Пауза активности:</strong> Вторая половина лимита откроется через <strong>${timeLeftMin} мин.</strong> для защиты IP от спам-фильтров.`;
        statusText.style.color = "var(--warning)";
    } else if (totalUsed >= 20) {
        statusText.innerHTML = "🚫 <strong>Лимит исчерпан:</strong> Суточный лимит 20 доменов полностью использован. Возвращайтесь завтра.";
        statusText.style.color = "var(--danger)";
    } else {
        if (firstUsed < 10) {
            statusText.innerHTML = `Доступно еще <strong>${10 - firstUsed} проверок</strong> до защитной паузы (1.5 часа).`;
            statusText.style.color = "var(--text-secondary)";
        } else {
            statusText.innerHTML = `Вторая половина лимита активна. Доступно еще <strong>${10 - secondUsed} проверок</strong> на сегодня.`;
            statusText.style.color = "var(--success)";
        }
    }
}

// Global click-to-copy handler with quick feedback
window.copyText = async function(text, element) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.setAttribute("readonly", "");
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            document.body.removeChild(textarea);
        }

        if (!element) return;
        const originalText = element.innerText;
        element.style.color = "var(--success)";
        element.innerText = "Скопировано!";
        setTimeout(() => {
            element.style.color = "";
            element.innerText = originalText;
        }, 1000);
    } catch (err) {
        console.error("Error copying text:", err);
    }
};

const readApiJson = async (response) => {
    const text = await response.text();
    try {
        return JSON.parse(text);
    } catch (error) {
        if (!text || !text.trim()) {
            throw new Error(`Сервер вернул пустой ответ (${response.status}). Попробуйте повторить проверку.`);
        }

        const plainText = text
            .replace(/<script[\s\S]*?<\/script>/gi, " ")
            .replace(/<style[\s\S]*?<\/style>/gi, " ")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim();
        const details = plainText ? ` ${plainText.slice(0, 120)}` : "";
        throw new Error(`Сервер вернул техническую страницу вместо ответа проверки (${response.status}).${details}`);
    }
};

// Single Email Finder and SMTP Validator with Multi-Domain support & Cooldown tracking
function initSingleEnricher() {
    const form = document.getElementById("enrich-form");
    const submitBtn = document.getElementById("submit-enrich-btn");
    const resultsWrapper = document.getElementById("results-wrapper");
    const emptyStateView = document.getElementById("empty-state-view");
    const domainReportList = document.getElementById("domain-report-list");
    const mxTableBody = document.getElementById("mx-table-body");
    const exportBtn = document.getElementById("export-csv-btn");
    const actionsBar = document.getElementById("results-actions-bar");
    const mxSection = document.getElementById("mx-results-section");
    const filterInput = document.getElementById("quick-filter-input");
    
    let currentLeads = [];

    const setSubmitDefault = () => {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `
            <span>Начать проверку</span>
            <svg class="btn-icon-right" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="5" y1="12" x2="19" y2="12"/>
                <polyline points="12 5 19 12 12 19"/>
            </svg>
        `;
    };

    const setWorkspaceLoading = (message) => {
        openResultsWorkspace();
        resultsWrapper.style.display = "none";
        emptyStateView.style.display = "flex";
        const title = emptyStateView.querySelector("h2");
        const text = emptyStateView.querySelector("p");
        if (title) title.textContent = "Проверка запущена";
        if (text) text.textContent = message;
    };

    const hideWorkspace = () => {
        resultsWrapper.style.display = "none";
        emptyStateView.style.display = "none";
        closeResultsWorkspace();
    };

    const showFullResultsShell = () => {
        openResultsWorkspace();
        emptyStateView.style.display = "none";
        resultsWrapper.style.display = "flex";
        domainReportList.style.display = "flex";
        if (actionsBar) actionsBar.style.display = "flex";
        mxSection.style.display = "none";
    };

    const showMxResultsShell = () => {
        openResultsWorkspace();
        emptyStateView.style.display = "none";
        resultsWrapper.style.display = "flex";
        domainReportList.style.display = "none";
        if (actionsBar) actionsBar.style.display = "none";
        mxSection.style.display = "flex";
    };

    const scrollToReportStartOnMobile = () => {
        if (!window.matchMedia("(max-width: 768px)").matches) return;

        const target = domainReportList.querySelector(".domain-report-block") || domainReportList || resultsWrapper;
        if (!target) return;

        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
                target.scrollIntoView({
                    behavior: prefersReducedMotion ? "auto" : "smooth",
                    block: "start"
                });
            });
        });
    };

    const renderMxLookup = async (rawDomains) => {
        const domains = rawDomains.map(d => normalizeDomainInput(d) || d);

        submitBtn.innerHTML = `<span>Проверка MX (${domains.length})...</span> <span class="pulse-dot"></span>`;
        setWorkspaceLoading("Проверяем почтовые записи доменов. Таблица откроется после ответа сервера.");
        mxTableBody.innerHTML = "";

        const response = await fetch("/api/check-mx-bulk", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ domains })
        });

        if (!response.ok) throw new Error("Ошибка связи с сервером");
        const data = await readApiJson(response);
        if (!data.success) throw new Error(data.error || "Не удалось проверить MX");

        data.results.forEach(res => {
            const tr = document.createElement("tr");
            const badgeClass = res.success ? "verified" : "invalid";
            const statusText = res.success ? "Активна" : "Нет почты";
            const recordsList = res.records.length > 0
                ? res.records.map(r => `<code>${escapeHtml(r)}</code>`).join("<br>")
                : '<span class="text-muted">MX-записи не найдены</span>';

            tr.innerHTML = `
                <td><strong>${escapeHtml(res.domain)}</strong></td>
                <td><span class="status-badge ${badgeClass}">${statusText}</span></td>
                <td><strong>${escapeHtml(res.provider)}</strong></td>
                <td style="font-size: 0.85rem;">${recordsList}</td>
            `;
            mxTableBody.appendChild(tr);
        });

        if (mxTableBody.children.length === 0) {
            mxTableBody.innerHTML = `<tr><td colspan="4" class="empty-state">Нет доменов для проверки.</td></tr>`;
        }

        showMxResultsShell();
    };

    // Real-time text search filter for tables
    if (filterInput) {
        filterInput.addEventListener("input", (e) => {
            const query = e.target.value.toLowerCase().trim();
            const blocks = domainReportList.querySelectorAll(".domain-report-block");
            blocks.forEach(block => {
                const text = block.textContent.toLowerCase();
                block.style.display = text.includes(query) ? "" : "none";
            });
        });
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const rawDomains = parseDomainListInput(document.getElementById("domain-input").value);
        
        const firstName = document.getElementById("first-name").value.trim();
        const lastName = document.getElementById("last-name").value.trim();
        
        if (rawDomains.length === 0) {
            hideWorkspace();
            return;
        }
        
        // Setup initial loading UI state
        submitBtn.disabled = true;
        setWorkspaceLoading(`Обрабатываем ${rawDomains.length} домен(ов). Результаты появятся справа после первой проверки.`);
        
        domainReportList.innerHTML = "";
        mxTableBody.innerHTML = "";
        if (filterInput) filterInput.value = "";
        currentLeads = [];

        let globalLogIndex = 0;
        let showWorkspace = false;

        const createDomainReportSection = (domainLabel) => {
            const displayDomain = String(domainLabel || "").trim() || "Домен без названия";
            const section = document.createElement("section");
            section.className = "domain-report-block";
            section.innerHTML = `
                <div class="domain-report-divider">
                    <span>Отчет по домену</span>
                    <strong>${escapeHtml(displayDomain)}</strong>
                </div>

                <div class="company-profile-summary">
                    <h3>Сводные данные по компании</h3>
                    <div class="domain-summary-list"></div>
                </div>

                <div class="results-section domain-email-section">
                    <h4>Информация по домену, почте и найденным почтовым ящикам</h4>
                    <div class="table-responsive">
                        <table class="leads-table">
                            <thead>
                                <tr>
                                    <th>Домен</th>
                                    <th>Email</th>
                                    <th>Результат</th>
                                    <th>Пояснение</th>
                                    <th>Действие</th>
                                </tr>
                            </thead>
                            <tbody class="domain-email-body"></tbody>
                        </table>
                    </div>
                </div>

                <div class="results-section domain-phone-section">
                    <h4>Найденные телефонные линии и добавочные</h4>
                    <div class="table-responsive">
                        <table class="leads-table">
                            <thead>
                                <tr>
                                    <th>Домен</th>
                                    <th>Номер телефона</th>
                                    <th>Добавочный</th>
                                    <th>Отдел / Назначение</th>
                                    <th>Источник (URL)</th>
                                </tr>
                            </thead>
                            <tbody class="domain-phone-body"></tbody>
                        </table>
                    </div>
                </div>
            `;
            domainReportList.appendChild(section);
            return {
                section,
                summaryList: section.querySelector(".domain-summary-list"),
                emailBody: section.querySelector(".domain-email-body"),
                phoneBody: section.querySelector(".domain-phone-body")
            };
        };

        const renderSummaryChips = (items, className = "") => {
            if (!items || items.length === 0) {
                return '<span class="summary-empty-text">Не найдены</span>';
            }
            return items.map(item => (
                `<span class="summary-chip ${className}">${escapeHtml(item)}</span>`
            )).join("");
        };

        const renderSocialSummaryLinks = (socials) => {
            const uniqueSocials = getUniqueSocials(socials);
            if (!uniqueSocials || uniqueSocials.length === 0) {
                return '<span class="summary-empty-text">Не найдены</span>';
            }
            return uniqueSocials.map(social => {
                const label = social.platform || "Ссылка";
                return `
                    <a href="${escapeAttr(social.url)}" target="_blank" rel="noopener noreferrer" class="summary-chip summary-chip-link">
                        ${escapeHtml(label)}
                    </a>
                `;
            }).join("");
        };

        const renderDomainSummaryCard = (summaryList, domainInput, data, companyDisplayName, faviconUrl, routeText) => {
            const requisites = data.requisites || {};
            const innList = Array.isArray(requisites.inn) ? Array.from(new Set(requisites.inn)) : [];
            const technologies = Array.isArray(data.technologies)
                ? Array.from(new Set(data.technologies.filter(Boolean)))
                : [];
            const providerText = data.provider
                ? `${data.provider}${routeText}`
                : "Не определен";

            const card = document.createElement("article");
            card.className = "domain-summary-card";
            card.innerHTML = `
                <div class="domain-summary-header">
                    <img src="${escapeAttr(faviconUrl)}" alt="" onerror="this.style.display='none'">
                    <div>
                        <strong>${escapeHtml(companyDisplayName)}</strong>
                        <span>${escapeHtml(domainInput)}</span>
                    </div>
                </div>
                <div class="domain-summary-grid">
                    <section class="domain-summary-item">
                        <h5>Почтовый провайдер</h5>
                        <p>${escapeHtml(providerText)}</p>
                    </section>
                    <section class="domain-summary-item">
                        <h5>Найденные ИНН</h5>
                        <div class="summary-chip-list">${renderSummaryChips(innList)}</div>
                    </section>
                    <section class="domain-summary-item">
                        <h5>Социальные сети</h5>
                        <div class="summary-chip-list">${renderSocialSummaryLinks(data.socials)}</div>
                    </section>
                    <section class="domain-summary-item">
                        <h5>Технологии на сайте</h5>
                        <div class="summary-chip-list">${renderSummaryChips(technologies, "summary-chip-tech")}</div>
                    </section>
                </div>
            `;
            summaryList.appendChild(card);
        };

        const getLeadStatusView = (lead) => {
            if (!lead || lead.mxStatus !== "Активен" || lead.smtpStatus === "invalid") {
                return { badgeClass: "invalid", text: "Не работает" };
            }
            if (lead.smtpStatus === "verified") {
                return { badgeClass: "verified", text: "Работает" };
            }
            return { badgeClass: "risky", text: "Невозможно проверить" };
        };

        const getLeadExplanation = (lead) => {
            const result = getLeadStatusView(lead).text;
            const validationDomain = lead?.validationDomain || "";
            const reason = String(lead?.reason || "");
            const reasonLower = reason.toLowerCase();
            const risk = String(lead?.risk || "");

            if (result === "Работает") {
                return validationDomain
                    ? `Почтовый сервер домена ${validationDomain} подтвердил этот адрес.`
                    : "Почтовый сервер подтвердил этот адрес.";
            }
            if (result === "Не работает") {
                if (lead?.mxStatus !== "Активен") {
                    return validationDomain
                        ? `Домен ${validationDomain} не принимает почту.`
                        : "Домен не принимает почту.";
                }
                return "Почтовый сервер отказал этому адресу.";
            }
            if (reasonLower.includes("случайный") || risk.includes("Catch-All")) {
                return "Домен принимает случайные адреса, поэтому конкретные ящики на этом домене невозможно проверить точно.";
            }
            if (reasonLower.includes("порт 25") || reasonLower.includes("порт")) {
                return "Не удалось выполнить точную SMTP-проверку: порт 25 недоступен.";
            }
            return "Почтовый сервер не дал однозначного ответа.";
        };

        const shouldShowLead = (lead) => {
            if (!lead || lead.mxStatus !== "Активен" || lead.smtpStatus === "invalid") return false;
            return lead.source !== "person" || lead.smtpStatus === "verified";
        };

        const appendHiddenEmailNotice = (emailBody, domainLabel, hiddenCount, inactiveCount, invalidCount) => {
            if (!hiddenCount) return;

            const details = [];
            const notWorkingCount = inactiveCount + invalidCount;
            const unknownCount = Math.max(0, hiddenCount - notWorkingCount);
            if (notWorkingCount) details.push(`${notWorkingCount} не работают`);
            if (unknownCount) details.push(`${unknownCount} невозможно проверить`);

            const tr = document.createElement("tr");
            tr.className = "hidden-email-row";
            tr.innerHTML = `
                <td colspan="5">
                    <strong>Убрано из основного списка: ${escapeHtml(hiddenCount)} проверенных вариантов.</strong>
                    ${details.length ? `${escapeHtml(details.join(", "))}. ` : ""}
                    Полный список можно открыть стрелкой в блоке проверенных вариантов.
                </td>
            `;
            emailBody.appendChild(tr);
        };

        const appendExternalEmailNotice = (emailBody, externalEmails = []) => {
            const emails = Array.from(new Set((externalEmails || []).filter(Boolean)));
            if (emails.length === 0) return;

            const visibleEmails = emails.slice(0, 6);
            const restCount = Math.max(0, emails.length - visibleEmails.length);
            const tr = document.createElement("tr");
            tr.className = "external-email-row";
            tr.innerHTML = `
                <td colspan="5">
                    <strong>На страницах найдены email других доменов.</strong>
                    ${visibleEmails.map(email => `<code>${escapeHtml(email)}</code>`).join(" ")}
                    ${restCount ? `<span class="text-muted">и еще ${escapeHtml(restCount)}</span>` : ""}
                    <span>Они не проверяются как контакты этой компании.</span>
                </td>
            `;
            emailBody.appendChild(tr);
        };

        const appendCheckedVariants = (emailBody, domainLabel, variants = []) => {
            if (!variants.length) return;

            const rows = variants.map(variant => {
                const status = getLeadStatusView(variant);
                return `
                    <tr>
                        <td><code>${escapeHtml(variant.pattern)}</code></td>
                        <td><code>${escapeHtml(variant.email)}</code></td>
                        <td><span class="status-badge ${status.badgeClass}">${escapeHtml(status.text)}</span></td>
                        <td>${escapeHtml(getLeadExplanation(variant))}</td>
                    </tr>
                `;
            }).join("");

            const tr = document.createElement("tr");
            tr.className = "variant-details-row";
            tr.innerHTML = `
                <td colspan="5">
                    <details>
                        <summary>Проверенные варианты написания почты для ${escapeHtml(domainLabel)} (${escapeHtml(variants.length)})</summary>
                        <div class="variant-details-content">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Шаблон</th>
                                        <th>Email</th>
                                        <th>Результат</th>
                                        <th>Пояснение</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        </div>
                    </details>
                </td>
            `;
            emailBody.appendChild(tr);
        };

        const appendEmailMessage = (emailBody, domainLabel, message, tone = "muted") => {
            const color = tone === "danger"
                ? "var(--danger)"
                : tone === "warning"
                    ? "var(--warning)"
                    : "var(--text-secondary)";
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><code>${escapeHtml(domainLabel)}</code></td>
                <td colspan="4" class="text-muted" style="color: ${color};">${escapeHtml(message)}</td>
            `;
            emailBody.appendChild(tr);
        };

        const appendPhoneEmptyState = (phoneBody) => {
            if (phoneBody.children.length === 0) {
                phoneBody.innerHTML = `<tr><td colspan="5" class="empty-state">Телефонные линии и добавочные на страницах этого домена не найдены.</td></tr>`;
            }
        };
        
        // Process each domain sequentially
        for (let i = 0; i < rawDomains.length; i++) {
            const rawDomainLabel = rawDomains[i];
            const domainInput = normalizeDomainInput(rawDomainLabel);
            
            if (!domainInput) {
                showWorkspace = true;
                showFullResultsShell();
                const report = createDomainReportSection(rawDomainLabel);
                renderDomainSummaryCard(
                    report.summaryList,
                    rawDomainLabel,
                    { provider: "Проверка не выполнена", requisites: { inn: [] }, socials: [], technologies: [] },
                    rawDomainLabel,
                    "",
                    ""
                );
                appendEmailMessage(report.emailBody, rawDomainLabel, "Некорректный адрес. Введите домен или ссылку вида example.com или https://example.com/contacts.", "danger");
                appendPhoneEmptyState(report.phoneBody);
                continue;
            }
            
            // Show current progress on search button
            submitBtn.innerHTML = `<span>Проверка ${i + 1} из ${rawDomains.length} (${escapeHtml(domainInput)})...</span> <span class="pulse-dot"></span>`;
            
            try {
                const proxyPool = getProxyPoolConfig();
                const response = await fetch("/api/enrich", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ domain: domainInput, firstName, lastName, proxyPool })
                });
                
                const data = await readApiJson(response);
                
                // If blocked by limits (429 Rate Limit exceeded)
                if (response.status === 429) {
                    showWorkspace = true;
                    showFullResultsShell();
                    const report = createDomainReportSection(domainInput);
                    renderDomainSummaryCard(
                        report.summaryList,
                        domainInput,
                        { provider: "Проверка остановлена лимитом", requisites: { inn: [] }, socials: [], technologies: [] },
                        domainInput,
                        `https://www.google.com/s2/favicons?sz=32&domain=${domainInput}`,
                        ""
                    );
                    appendEmailMessage(report.emailBody, domainInput, data.error || "Лимит проверок исчерпан. Следующие домены не запускались.", "warning");
                    appendPhoneEmptyState(report.phoneBody);

                    alert(data.error);
                    if (data.limitStatus) renderLimits(data.limitStatus);
                    if (data.proxyStatus) renderProxyPoolStatus(data.proxyStatus);
                    break; // Stop further domains processing
                }
                
                if (!response.ok) throw new Error(data.error || "Ошибка связи с сервером");
                
                if (data.success) {
                    showWorkspace = true;
                    showFullResultsShell();
                    const report = createDomainReportSection(domainInput);
                    
                    // Render limits returning from API
                    if (data.limitStatus) renderLimits(data.limitStatus);
                    if (data.proxyStatus) renderProxyPoolStatus(data.proxyStatus);

                    // Render one summary card per checked domain.
                    const faviconUrl = `https://www.google.com/s2/favicons?sz=32&domain=${domainInput}`;
                    const companyDisplayName = data.pageTitle ? data.pageTitle : domainInput;
                    const routeText = data.proxyUsed ? ` · ${data.proxyUsed}` : "";
                    renderDomainSummaryCard(report.summaryList, domainInput, data, companyDisplayName, faviconUrl, routeText);

                    if (data.catchAllDetected) {
                        const warningTr = document.createElement("tr");
                        warningTr.className = "catch-all-row";
                        warningTr.innerHTML = `
                            <td colspan="5">
                                <strong>${escapeHtml(domainInput)} принимает случайные адреса.</strong>
                                Поэтому конкретные ящики на этом домене невозможно проверить точно.
                            </td>
                        `;
                        report.emailBody.appendChild(warningTr);
                    }
                    
                    // Render Email Leads
                    const visibleLeads = (data.leads || []).filter(shouldShowLead);
                    if (visibleLeads.length > 0) {
                        visibleLeads.forEach(l => {
                            // Cache domain in lead object for CSV exporter
                            l.domain = domainInput;
                            currentLeads.push(l);
                            
                            const tr = document.createElement("tr");
                            const rowLogIndex = globalLogIndex;
                            const status = getLeadStatusView(l);
                            
                            const sourceBadge = l.pattern === 'Найдено на сайте' 
                                ? ' <span class="status-badge verified" style="font-size:0.65rem; padding: 0.1rem 0.4rem; vertical-align: middle; margin-left: 0.4rem; text-transform: none;">Найден на сайте</span>' 
                                : '';
                                
                            const validationDomainText = l.validationDomain && l.validationDomain !== domainInput
                                ? `${domainInput} → ${l.validationDomain}`
                                : domainInput;
                                
                            tr.innerHTML = `
                                <td><code>${escapeHtml(validationDomainText)}</code></td>
                                <td><strong class="clickable-copy" data-copy="${escapeAttr(l.email)}">${escapeHtml(l.email)}</strong>${sourceBadge}</td>
                                <td><span class="status-badge ${status.badgeClass}">${escapeHtml(status.text)}</span></td>
                                <td title="${escapeAttr(l.reason)}">${escapeHtml(getLeadExplanation(l))}</td>
                                <td>
                                    <button class="text-btn" data-log-index="${rowLogIndex}">Лог</button>
                                </td>
                            `;
                            report.emailBody.appendChild(tr);

                            const copyEl = tr.querySelector("[data-copy]");
                            if (copyEl) {
                                copyEl.addEventListener("click", () => copyText(l.email, copyEl));
                            }
                            const logBtn = tr.querySelector("[data-log-index]");
                            if (logBtn) {
                                logBtn.addEventListener("click", () => toggleLog(rowLogIndex));
                            }
                            
                            // Hidden Log Details Row
                            const logTr = document.createElement("tr");
                            logTr.id = `log-row-${rowLogIndex}`;
                            logTr.style.display = "none";
                            logTr.className = "log-row-container";
                            logTr.innerHTML = `
                                <td colspan="5">
                                    <div class="log-box">
                                        <div class="log-title">Служебный SMTP лог проверки (${escapeHtml(domainInput)})</div>
                                        ${escapeHtml(l.log)}
                                    </div>
                                </td>
                            `;
                            report.emailBody.appendChild(logTr);
                            globalLogIndex++;
                        });
                    }

                    appendCheckedVariants(report.emailBody, domainInput, data.checkedVariants || []);
                    appendHiddenEmailNotice(
                        report.emailBody,
                        domainInput,
                        data.hiddenEmailCount || 0,
                        data.hiddenInactiveEmailCount || 0,
                        data.hiddenInvalidEmailCount || 0
                    );
                    appendExternalEmailNotice(report.emailBody, data.externalEmails || []);
                    if (report.emailBody.children.length === 0) {
                        appendEmailMessage(report.emailBody, domainInput, "Рабочие почтовые ящики по этому домену не найдены.");
                    }
                    
                    // Render Scraped Phone lines
                    if (data.phones && data.phones.length > 0) {
                        data.phones.forEach(phone => {
                            const tr = document.createElement("tr");
                            let path = '/';
                            try {
                                const parsedUrl = new URL(phone.sourceUrl);
                                path = parsedUrl.pathname + parsedUrl.search;
                                if (path === '/') path = 'Главная';
                            } catch (e) {
                                path = 'Ссылка';
                            }

                            const sourceUrl = String(phone.sourceUrl || "");
                            const safeSourceUrl = /^https?:\/\//i.test(sourceUrl) ? sourceUrl : "#";
                            
                            tr.innerHTML = `
                                <td><code>${escapeHtml(domainInput)}</code></td>
                                <td><strong class="clickable-copy" data-copy="${escapeAttr(phone.phone)}">${escapeHtml(phone.phone)}</strong></td>
                                <td>${phone.extension ? `<span class="status-badge loading">доб. ${escapeHtml(phone.extension)}</span>` : '<span class="text-muted">-</span>'}</td>
                                <td><strong>${escapeHtml(phone.department)}</strong></td>
                                <td><a href="${escapeAttr(safeSourceUrl)}" target="_blank" rel="noopener noreferrer" class="text-btn" style="font-size: 0.8rem;">${escapeHtml(path)}</a></td>
                            `;
                            report.phoneBody.appendChild(tr);

                            const copyEl = tr.querySelector("[data-copy]");
                            if (copyEl) {
                                copyEl.addEventListener("click", () => copyText(phone.phone, copyEl));
                            }
                        });
                    }
                    appendPhoneEmptyState(report.phoneBody);
                }
            } catch (err) {
                console.error(`Error processing ${domainInput}:`, err);
                showWorkspace = true;
                showFullResultsShell();
                const failedDomain = domainInput || rawDomainLabel;
                const report = createDomainReportSection(failedDomain);
                renderDomainSummaryCard(
                    report.summaryList,
                    failedDomain,
                    { provider: "Проверка не завершена", requisites: { inn: [] }, socials: [], technologies: [] },
                    failedDomain,
                    domainInput ? `https://www.google.com/s2/favicons?sz=32&domain=${domainInput}` : "",
                    ""
                );
                appendEmailMessage(report.emailBody, failedDomain, `Ошибка сбора: ${err.message}`, "danger");
                appendPhoneEmptyState(report.phoneBody);
            }
        }
        
        // Show empty states if no data was loaded
        if (showWorkspace) {
            if (domainReportList.children.length === 0) {
                domainReportList.innerHTML = '<div class="summary-empty-state">Результаты проверки отсутствуют.</div>';
            }
        }

        if (!showWorkspace) {
            hideWorkspace();
        }

        setSubmitDefault();
        if (showWorkspace) {
            scrollToReportStartOnMobile();
        }
    });
    
    // Export unified leads list to CSV
    if (exportBtn) exportBtn.addEventListener("click", () => {
        if (currentLeads.length === 0) return;
        
        let csvContent = "data:text/csv;charset=utf-8,\uFEFF";
        csvContent += "Domain,Email,Result,Details\r\n";
        
        currentLeads.forEach(lead => {
            const status = getLeadStatusView(lead);
            csvContent += [
                lead.domain,
                lead.email,
                status.text,
                getLeadExplanation(lead)
            ].map(csvCell).join(",") + "\r\n";
        });
        
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `leads_enrichment_export.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    });
}

// Global function to toggle SMTP log row visibility
window.toggleLog = function(index) {
    const logRow = document.getElementById(`log-row-${index}`);
    if (logRow.style.display === "none") {
        logRow.style.display = "table-row";
    } else {
        logRow.style.display = "none";
    }
};
