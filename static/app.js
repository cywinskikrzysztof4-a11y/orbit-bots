// Orbit Bots — Client JavaScript (Vanilla JS, Zero Dependencies)

let currentBot = "flights";
let routesData = [];
let selectedRouteId = null;
let vastStatus = {};

document.addEventListener("DOMContentLoaded", () => {
  initApp();
  // Okresowe odświeżanie danych co 15 sekund
  setInterval(refreshPeriodicData, 15000);

  // Sprawdź czy nastąpił powrót z autoryzacji Gmail OAuth
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has("gmail_connected")) {
    switchBot("accounts");
    alert("🎉 Pomyślnie podłączono konto Gmail (tryb tylko do odczytu)!");
    window.history.replaceState({}, document.title, window.location.pathname);
  }
});

async function initApp() {
  await Promise.all([
    checkVastStatus(),
    loadAlerts(),
    loadRoutes(),
    loadDeals(),
    loadChatHistory(),
    loadFlightChatHistory(),
    loadVideoChatHistory(),
    loadVideoJobs(),
    loadAccountsData()
  ]);
}

function refreshPeriodicData() {
  checkVastStatus();
  loadAlerts();
  if (currentBot === "flights") {
    loadRoutes(false);
  } else if (currentBot === "video") {
    loadVideoJobs(false);
  } else if (currentBot === "accounts") {
    loadAccountsData(false);
  }
}

// Przełączanie aktywnego bota lub strony
function switchBot(botId) {
  currentBot = botId;
  document.querySelectorAll(".bot-nav-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-bot") === botId);
  });
  document.querySelectorAll(".bot-view").forEach(view => {
    view.classList.toggle("active", view.id === `view-${botId}`);
  });
  if (botId === "accounts") {
    loadAccountsData();
  }
}

// ---------------- VAST.AI KONTROLER ----------------
async function checkVastStatus() {
  try {
    const res = await fetch("/api/vast/status");
    if (!res.ok) return;
    vastStatus = await res.json();

    const badge = document.getElementById("vastStatusBadge");
    const dphEl = document.getElementById("vastDph");
    const costEl = document.getElementById("vastSessionCost");
    const timeEl = document.getElementById("vastSessionTime");
    const startBtn = document.getElementById("btnStartVast");
    const stopBtn = document.getElementById("btnStopVast");
    const idleNote = document.getElementById("vastIdleNote");

    const st = vastStatus.state || "unknown";
    badge.textContent = st;
    badge.className = "badge";

    if (st === "running") {
      badge.classList.add("badge-status-running");
      startBtn.disabled = true;
      stopBtn.disabled = false;
      document.getElementById("dot-video").className = "status-dot dot-green";
    } else if (st === "starting") {
      badge.classList.add("badge-status-starting");
      startBtn.disabled = true;
      stopBtn.disabled = false;
      document.getElementById("dot-video").className = "status-dot dot-blue";
    } else {
      badge.classList.add("badge-status-stopped");
      startBtn.disabled = false;
      stopBtn.disabled = true;
      if (st.includes("brak klucza")) {
        document.getElementById("dot-video").className = "status-dot dot-orange";
      } else {
        document.getElementById("dot-video").className = "status-dot dot-green";
      }
    }

    dphEl.textContent = `${(vastStatus.dph || 0.12).toFixed(2)} $/h`;
    costEl.textContent = `${(vastStatus.session_cost || 0).toFixed(4)} $`;
    timeEl.textContent = `${vastStatus.session_minutes || 0} min`;
    idleNote.textContent = vastStatus.enabled
      ? "Auto-stop: po 10 min bezczynności"
      : "Vast wyłączony (Faza 1 — zero wydatków)";
  } catch (e) {
    console.error("Błąd sprawdzania Vast:", e);
  }
}

function confirmStartVast() {
  openModal("confirmVastModal");
}

async function startVastConfirmed() {
  closeModal("confirmVastModal");
  const banner = document.getElementById("gpuStartingBanner");
  if (banner) banner.style.display = "block";
  try {
    const res = await fetch("/api/vast/start", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Błąd uruchamiania Vast.ai: " + (data.detail || data.error));
    } else {
      await checkVastStatus();
    }
  } catch (e) {
    alert("Błąd połączenia: " + e);
  } finally {
    setTimeout(() => { if (banner) banner.style.display = "none"; }, 8000);
  }
}

async function stopVast() {
  if (!confirm("Czy na pewno chcesz zatrzymać instancję GPU Vast.ai?")) return;
  try {
    const res = await fetch("/api/vast/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) alert("Błąd zatrzymywania: " + (data.detail || data.error));
    else await checkVastStatus();
  } catch (e) {
    alert("Błąd połączenia: " + e);
  }
}

// ---------------- ALERTY SYSTEMOWE ----------------
async function loadAlerts() {
  try {
    const res = await fetch("/api/alerts?limit=50");
    if (!res.ok) return;
    const alerts = await res.json();

    const unread = alerts.filter(a => !a.read);
    const unreadCount = unread.length;
    document.getElementById("totalAlertsCount").textContent = unreadCount;

    const countByBot = {};
    alerts.forEach(a => {
      if (!a.read) countByBot[a.bot] = (countByBot[a.bot] || 0) + 1;
    });

    ["flights", "daily", "video"].forEach(b => {
      const el = document.getElementById(`badge-${b}`);
      if (el) el.textContent = countByBot[b] || 0;
    });

    const container = document.getElementById("alertsListContainer");
    if (!alerts.length) {
      container.innerHTML = `<div class="text-muted" style="text-align:center; padding: 20px;">Brak zarejestrowanych alertów.</div>`;
      return;
    }

    container.innerHTML = alerts.map(a => `
      <div class="alert-item ${a.read ? 'read' : 'unread'}">
        <div class="alert-header">
          <span class="alert-bot-badge alert-bot-${a.bot}">${a.bot}</span>
          <span class="alert-title">${escapeHtml(a.title)}</span>
          <span class="alert-time">${a.created}</span>
        </div>
        <div class="alert-body">${escapeHtml(a.message)}</div>
      </div>
    `).join("");
  } catch (e) {
    console.error("Błąd ładowania alertów:", e);
  }
}

async function markAllAlertsRead() {
  try {
    await fetch("/api/alerts/read", { method: "POST" });
    await loadAlerts();
  } catch (e) {
    alert("Błąd oznaczania alertów: " + e);
  }
}

// ---------------- BOT 1: ŁOWCA LOTÓW ----------------
async function loadRoutes(updateChart = true) {
  try {
    const res = await fetch("/api/flights/routes");
    routesData = await res.json();

    const countEl = document.getElementById("routesCount");
    if (countEl) countEl.textContent = `${routesData.length} tras`;

    const container = document.getElementById("routesList");
    if (!routesData.length) {
      container.innerHTML = `<div class="text-muted" style="padding: 20px; text-align: center;">Brak monitorowanych tras. Kliknij „+ Dodaj trasę”.</div>`;
      if (updateChart) document.getElementById("chartCard").style.display = "none";
      return;
    }

    container.innerHTML = routesData.map(r => {
      const last = r.history && r.history.length ? r.history[r.history.length - 1] : null;
      const minPrice = last ? `${last.min_price} ${last.currency}` : "Brak danych";
      const isSelected = r.id === selectedRouteId;

      return `
        <div class="route-card ${isSelected ? 'selected' : ''}" onclick="selectRoute(${r.id})">
          <div class="route-meta">
            <div class="route-badges">
              <span class="iata-badge">${r.origin} ➔ ${r.dest}</span>
              <span class="route-month">${r.month} • ${r.provider}</span>
            </div>
          </div>
          <div class="route-pricing">
            <div class="current-price">${minPrice}</div>
            <div class="price-limits">
              ${r.threshold ? `Próg: ≤${r.threshold} PLN` : ''}
              ${r.drop_pct ? `Spadek: ≥${r.drop_pct}%` : ''}
            </div>
          </div>
          <div class="route-actions" onclick="event.stopPropagation()">
            <button class="btn btn-sm btn-outline" title="Sprawdź teraz" onclick="checkRoute(${r.id})">🔍</button>
            <button class="btn btn-sm btn-outline-danger" title="Usuń" onclick="deleteRoute(${r.id})">✕</button>
          </div>
        </div>
      `;
    }).join("");

    if (updateChart) {
      if (!selectedRouteId && routesData.length) {
        selectRoute(routesData[0].id);
      } else if (selectedRouteId) {
        selectRoute(selectedRouteId);
      }
    }
  } catch (e) {
    console.error("Błąd ładowania tras:", e);
  }
}

function selectRoute(id) {
  selectedRouteId = id;
  document.querySelectorAll(".route-card").forEach(c => c.classList.remove("selected"));
  const found = routesData.find(r => r.id === id);
  if (!found) return;

  const card = document.getElementById("chartCard");
  card.style.display = "block";
  document.getElementById("chartTitle").textContent = `Wykres cen: ${found.origin} ➔ ${found.dest} (${found.month})`;

  renderSvgChart(found.history || []);
  renderDayBars(found.days || []);
}

function renderSvgChart(history) {
  const container = document.getElementById("svgChartContainer");
  if (!history || history.length < 2) {
    container.innerHTML = `<div class="chart-empty-state">Za mało danych historycznych do narysowania linii trendu (wymagane min. 2 pomiary). Kliknij 🔍 aby sprawdzić ponownie.</div>`;
    return;
  }

  const width = container.clientWidth || 550;
  const height = 180;
  const pad = 30;

  const prices = history.map(h => h.min_price);
  const minP = Math.min(...prices) * 0.9;
  const maxP = Math.max(...prices) * 1.1;

  const pts = history.map((h, i) => {
    const x = pad + (i / (history.length - 1)) * (width - 2 * pad);
    const y = height - pad - ((h.min_price - minP) / (maxP - minP || 1)) * (height - 2 * pad);
    return `${x},${y}`;
  }).join(" ");

  container.innerHTML = `
    <svg width="${width}" height="${height}">
      <polyline fill="none" stroke="#22d3ee" stroke-width="2.5" points="${pts}" />
      ${history.map((h, i) => {
        const x = pad + (i / (history.length - 1)) * (width - 2 * pad);
        const y = height - pad - ((h.min_price - minP) / (maxP - minP || 1)) * (height - 2 * pad);
        return `<circle cx="${x}" cy="${y}" r="4" fill="#7c5cff" stroke="#fff" stroke-width="1.5"><title>${h.checked.slice(5,16)}: ${h.min_price} ${h.currency}</title></circle>`;
      }).join("")}
    </svg>
  `;
}

function renderDayBars(days) {
  const container = document.getElementById("dayBarsContainer");
  if (!days || !days.length) {
    container.innerHTML = "";
    return;
  }

  const prices = days.map(d => d.price);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);

  container.innerHTML = `
    <div style="font-size:0.8rem; color:var(--text-muted); margin: 8px 0;">Ceny poszczególnych dni w miesiącu (zielony = najtaniej):</div>
    <div class="bars-grid">
      ${days.map(d => {
        const isMin = d.price === minP;
        const hPct = Math.max(15, Math.round(((d.price - minP) / (maxP - minP || 1)) * 70 + 20));
        return `
          <div class="bar-col" title="${d.date}: ${d.price} ${d.currency}">
            <div class="bar-fill ${isMin ? 'min-bar' : ''}" style="height:${hPct}%;"></div>
            <span class="bar-date">${d.date.slice(8, 10)}</span>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function showAddRouteModal() {
  openModal("addRouteModal");
}

async function submitNewRoute(e) {
  e.preventDefault();
  const origin = document.getElementById("newRouteOrigin").value;
  const dest = document.getElementById("newRouteDest").value.toUpperCase().trim();
  const month = document.getElementById("newRouteMonth").value;
  const th = document.getElementById("newRouteThreshold").value;
  const drop = document.getElementById("newRouteDrop").value;

  try {
    const res = await fetch("/api/flights/routes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin,
        dest,
        month,
        provider: "ryanair",
        threshold: th ? parseFloat(th) : null,
        drop_pct: drop ? parseFloat(drop) : null
      })
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Błąd: " + (data.detail || data.error));
      return;
    }
    closeModal("addRouteModal");
    await loadRoutes();
    await loadAlerts();
  } catch (err) {
    alert("Błąd połączenia: " + err);
  }
}

async function checkRoute(id, test = false) {
  try {
    const res = await fetch(`/api/flights/routes/${id}/check?test=${test ? "true" : "false"}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      alert("Błąd sprawdzania: " + (data.detail || data.error));
      return;
    }
    await loadRoutes(false);
    await loadAlerts();
  } catch (err) {
    alert("Błąd: " + err);
  }
}

async function deleteRoute(id) {
  if (!confirm("Czy na pewno chcesz usunąć tę trasę i jej historię?")) return;
  try {
    await fetch(`/api/flights/routes/${id}`, { method: "DELETE" });
    if (selectedRouteId === id) selectedRouteId = null;
    await loadRoutes();
  } catch (err) {
    alert("Błąd usuwania: " + err);
  }
}

// ---------------- FLY4FREE RSS ----------------
async function loadDeals() {
  const container = document.getElementById("dealsFeed");
  try {
    const res = await fetch("/api/flights/deals");
    const deals = await res.json();
    document.getElementById("dealsCount").textContent = deals.length;

    if (!deals.length) {
      container.innerHTML = `<div class="text-muted" style="padding:15px; text-align:center;">Brak zapisanych okazji. Kliknij „Pobierz Fly4free”.</div>`;
      return;
    }

    container.innerHTML = deals.map(d => `
      <div class="deal-item">
        <a href="${d.link}" target="_blank" rel="noopener noreferrer">${escapeHtml(d.title)}</a>
        <div class="deal-meta">
          <span>${d.price || "Okazja"} • ${d.origin || "Polska"}</span>
          <span>${d.pub_date ? d.pub_date.slice(0, 16) : ""}</span>
        </div>
      </div>
    `).join("");
  } catch (e) {
    console.error("Błąd okazji:", e);
  }
}

async function refreshDeals() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "⏳ Pobieram...";
  try {
    const res = await fetch("/api/flights/deals/refresh", { method: "POST" });
    const data = await res.json();
    await loadDeals();
    await loadAlerts();
    alert(`Pobrano RSS: dodano ${data.new || 0} nowych wpisów (łącznie ${data.total_saved || 0}).`);
  } catch (e) {
    alert("Błąd pobierania RSS: " + e);
  } finally {
    btn.disabled = false;
    btn.textContent = "🔄 Pobierz Fly4free";
  }
}

// ---------------- RENDEROWANIE KROKÓW AGENTA (Wymóg 5) ----------------
function renderAgentStepsHtml(steps) {
  if (!steps || !steps.length) return "";
  return `
    <div class="agent-steps-container">
      <div class="agent-steps-header" onclick="this.parentElement.classList.toggle('collapsed')">
        <span>⚡</span> <strong>Wykonane kroki narzędzi (${steps.length}):</strong>
        <span class="steps-toggle-hint">(kliknij, aby zwinąć/rozwinąć)</span>
      </div>
      <div class="agent-steps-list">
        ${steps.map(s => `
          <div class="agent-step-item">
            <div class="step-tool-line">
              <span class="step-tool-name">🛠️ ${escapeHtml(s.tool)}</span>
              <span class="step-tool-args">${escapeHtml(JSON.stringify(s.arguments || {}))}</span>
            </div>
            <div class="step-tool-summary">➜ ${escapeHtml(s.result_summary || "")}</div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

// ---------------- BOT 2: DZIENNY (AGENT CHAT) ----------------
async function loadChatHistory() {
  try {
    const res = await fetch("/api/daily/history?session=default");
    const history = await res.json();
    const container = document.getElementById("chatMessages");
    if (!history.length) return;

    container.innerHTML = history.map(m => `
      <div class="msg-bubble ${m.role}">
        <div class="msg-author">${m.role === "user" ? "Ty" : "Dzienny"}</div>
        <div class="msg-text">${escapeHtml(m.content).replace(/\n/g, "<br>")}</div>
      </div>
    `).join("");
    container.scrollTop = container.scrollHeight;
  } catch (e) {
    console.error("Błąd historii czatu Dziennego:", e);
  }
}

async function sendChatMessage(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("chatInput");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  appendGenericChatMessage("chatMessages", "user", "Ty", msg);

  const btn = document.getElementById("btnSendChat");
  btn.disabled = true;

  try {
    const res = await fetch("/api/daily/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: "default", message: msg })
    });
    const data = await res.json();
    if (!res.ok) {
      appendGenericChatMessage("chatMessages", "assistant", "Dzienny", "⚠️ Błąd: " + (data.detail || data.error));
    } else {
      appendGenericChatMessage("chatMessages", "assistant", "Dzienny", data.answer || "Brak odpowiedzi", data.steps);
      if (data.paused) {
        loadAccountsData();
      }
    }
  } catch (err) {
    appendGenericChatMessage("chatMessages", "assistant", "Dzienny", "⚠️ Błąd połączenia: " + err);
  } finally {
    btn.disabled = false;
  }
}

function quickAsk(text) {
  document.getElementById("chatInput").value = text;
  sendChatMessage();
}

async function forgetMemory() {
  if (!confirm("Czy wyczyścić pamięć rozmów bota Dziennego dla tej sesji?")) return;
  try {
    await fetch("/api/daily/forget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: "default" })
    });
    document.getElementById("chatMessages").innerHTML = `
      <div class="msg-bubble assistant">
        <div class="msg-author">Dzienny</div>
        <div class="msg-text">Pamięć sesji została wyczyszczona. O czym chciałbyś porozmawiać?</div>
      </div>
    `;
  } catch (e) {
    alert("Błąd: " + e);
  }
}

// ---------------- CZAT AGENTA LOTNICZEGO ----------------
async function loadFlightChatHistory() {
  const container = document.getElementById("flightChatMessages");
  if (!container) return;
  try {
    const res = await fetch("/api/flights/history?session=default");
    const history = await res.json();
    if (!history.length) return;
    container.innerHTML = history.map(m => `
      <div class="msg-bubble ${m.role}">
        <div class="msg-author">${m.role === "user" ? "Ty" : "Łowca Lotów"}</div>
        <div class="msg-text">${escapeHtml(m.content).replace(/\n/g, "<br>")}</div>
      </div>
    `).join("");
    container.scrollTop = container.scrollHeight;
  } catch (e) {}
}

async function sendFlightChatMessage(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("flightChatInput");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  appendGenericChatMessage("flightChatMessages", "user", "Ty", msg);
  const btn = document.getElementById("btnSendFlightChat");
  btn.disabled = true;

  try {
    const res = await fetch("/api/flights/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: "default", message: msg })
    });
    const data = await res.json();
    if (!res.ok) {
      appendGenericChatMessage("flightChatMessages", "assistant", "Łowca Lotów", "⚠️ Błąd: " + (data.detail || data.error));
    } else {
      appendGenericChatMessage("flightChatMessages", "assistant", "Łowca Lotów", data.answer || "Brak odpowiedzi", data.steps);
      await loadRoutes(false);
      await loadAlerts();
    }
  } catch (err) {
    appendGenericChatMessage("flightChatMessages", "assistant", "Łowca Lotów", "⚠️ Błąd: " + err);
  } finally {
    btn.disabled = false;
  }
}

// ---------------- CZAT AGENTA WIDEO ----------------
async function loadVideoChatHistory() {
  const container = document.getElementById("videoChatMessages");
  if (!container) return;
  try {
    const res = await fetch("/api/video/history?session=default");
    const history = await res.json();
    if (!history.length) return;
    container.innerHTML = history.map(m => `
      <div class="msg-bubble ${m.role}">
        <div class="msg-author">${m.role === "user" ? "Ty" : "Agent Wideo"}</div>
        <div class="msg-text">${escapeHtml(m.content).replace(/\n/g, "<br>")}</div>
      </div>
    `).join("");
    container.scrollTop = container.scrollHeight;
  } catch (e) {}
}

async function sendVideoChatMessage(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("videoChatInput");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  appendGenericChatMessage("videoChatMessages", "user", "Ty", msg);
  const btn = document.getElementById("btnSendVideoChat");
  btn.disabled = true;

  try {
    const res = await fetch("/api/video/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: "default", message: msg })
    });
    const data = await res.json();
    if (!res.ok) {
      appendGenericChatMessage("videoChatMessages", "assistant", "Agent Wideo", "⚠️ Błąd: " + (data.detail || data.error));
    } else {
      appendGenericChatMessage("videoChatMessages", "assistant", "Agent Wideo", data.answer || "Brak odpowiedzi", data.steps);
      await loadVideoJobs(false);
    }
  } catch (err) {
    appendGenericChatMessage("videoChatMessages", "assistant", "Agent Wideo", "⚠️ Błąd: " + err);
  } finally {
    btn.disabled = false;
  }
}

function appendGenericChatMessage(containerId, role, author, content, steps = null) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const div = document.createElement("div");
  div.className = `msg-bubble ${role}`;

  const stepsHtml = (role === "assistant" && steps && steps.length) ? renderAgentStepsHtml(steps) : "";

  div.innerHTML = `
    <div class="msg-author">${author}</div>
    ${stepsHtml}
    <div class="msg-text">${escapeHtml(content).replace(/\n/g, "<br>")}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ---------------- STRONA KONTA I ZGODY (Wymóg 4) ----------------
async function loadAccountsData(showLoader = true) {
  try {
    const [accRes, actRes, twoFaRes] = await Promise.all([
      fetch("/api/accounts"),
      fetch("/api/actions/pending"),
      fetch("/api/2fa/pending")
    ]);

    const accounts = accRes.ok ? await accRes.json() : [];
    const pendingActions = actRes.ok ? await actRes.json() : [];
    const pending2FA = twoFaRes.ok ? await twoFaRes.json() : [];

    // Liczniki
    document.getElementById("accountsCount").textContent = `${accounts.length} kont`;
    document.getElementById("pendingActionsCount").textContent = pendingActions.length;
    document.getElementById("pending2FACount").textContent = pending2FA.length;
    document.getElementById("badge-accounts").textContent = pendingActions.length + pending2FA.length;

    // Render kont
    const accListEl = document.getElementById("accountsListContainer");
    if (!accounts.length) {
      accListEl.innerHTML = `
        <div class="text-muted" style="padding:20px; text-align:center;">
          Brak podłączonych kont. Kliknij „Połącz Gmail (OAuth 2.0)” lub dodaj konto serwisowe poniżej.
        </div>
      `;
    } else {
      accListEl.innerHTML = accounts.map(a => `
        <div class="account-card-item">
          <div class="account-card-info">
            <h4>${escapeHtml(a.name)}</h4>
            <div class="account-meta">
              <span>Serwis: <strong>${a.service}</strong></span> • 
              <span>Typ: <strong>${a.auth_type}</strong></span> • 
              <span>Status: <strong class="${a.status === 'connected' ? 'text-green' : 'text-orange'}">${a.status}</strong></span>
            </div>
          </div>
          <div class="account-card-controls">
            <div class="consent-toggle-wrapper">
              <span>Zgoda agenta:</span>
              <label class="switch">
                <input type="checkbox" ${a.consent ? 'checked' : ''} onchange="toggleAccountConsent('${a.id}', this.checked)">
                <span class="slider"></span>
              </label>
            </div>
            <button class="btn btn-sm btn-outline-danger" onclick="disconnectAccount('${a.id}')">Odłącz</button>
          </div>
        </div>
      `).join("");
    }

    // Render kolejki akcji do zatwierdzenia
    const actionsEl = document.getElementById("pendingActionsList");
    if (!pendingActions.length) {
      actionsEl.innerHTML = `<div class="text-muted" style="text-align:center; padding:15px;">Brak oczekujących akcji do zatwierdzenia.</div>`;
    } else {
      actionsEl.innerHTML = pendingActions.map(act => `
        <div class="pending-action-item">
          <div>
            <div class="pending-action-desc"><strong>[${escapeHtml(act.agent_id)}] ${escapeHtml(act.action_type)}:</strong> ${escapeHtml(act.description)}</div>
            <div class="pending-action-meta">ID: ${act.id} • Utworzono: ${act.created}</div>
          </div>
          <div style="display:flex; gap:6px;">
            <button class="btn btn-sm btn-cyan" onclick="approveAction('${act.id}')">✓ Zatwierdź</button>
            <button class="btn btn-sm btn-outline-danger" onclick="rejectAction('${act.id}')">✕ Odrzuć</button>
          </div>
        </div>
      `).join("");
    }

    // Render oczekujących 2FA
    const twoFaEl = document.getElementById("pending2FAList");
    if (!pending2FA.length) {
      twoFaEl.innerHTML = `<div class="text-muted" style="text-align:center; padding:15px;">Brak oczekujących żądań 2FA.</div>`;
    } else {
      twoFaEl.innerHTML = pending2FA.map(req => `
        <div class="two-fa-item">
          <div style="font-weight:600; color:#f59e0b;">🔐 Wymagany kod 2FA dla konta: ${escapeHtml(req.account_id)}</div>
          <div style="font-size:0.85rem; margin-top:4px;">${escapeHtml(req.prompt)}</div>
          <form class="two-fa-form" onsubmit="submit2FACode(event, '${req.id}')">
            <input type="text" id="twofa_input_${req.id}" placeholder="Wpisz kod..." required autocomplete="one-time-code">
            <button type="submit" class="btn btn-sm btn-cyan">Prześlij kod</button>
          </form>
        </div>
      `).join("");
    }
  } catch (e) {
    console.error("Błąd pobierania danych kont:", e);
  }
}

async function toggleAccountConsent(accountId, consent) {
  try {
    const res = await fetch(`/api/accounts/${accountId}/consent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent })
    });
    if (!res.ok) alert("Błąd aktualizacji zgody");
    await loadAccountsData(false);
  } catch (e) {
    alert("Błąd połączenia: " + e);
  }
}

async function disconnectAccount(accountId) {
  if (!confirm(`Czy na pewno chcesz odłączyć konto '${accountId}' i usunąć jego poświadczenia z sejfu?`)) return;
  try {
    const res = await fetch(`/api/accounts/${accountId}`, { method: "DELETE" });
    if (!res.ok) alert("Błąd usuwania konta");
    await loadAccountsData();
  } catch (e) {
    alert("Błąd połączenia: " + e);
  }
}

async function submitCredentialsAccount(e) {
  e.preventDefault();
  const id = document.getElementById("accId").value.trim();
  const name = document.getElementById("accName").value.trim();
  const service = document.getElementById("accService").value.trim();
  const username = document.getElementById("accUsername").value.trim();
  const password = document.getElementById("accPassword").value;
  const consent = document.getElementById("accConsent").checked;

  try {
    const res = await fetch("/api/accounts/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name, service, username, password, consent })
    });
    if (!res.ok) {
      alert("Błąd zapisu konta");
      return;
    }
    alert(`Konto '${name}' zostało pomyślnie zaszyfrowane w sejfie Fernet i zarejestrowane!`);
    document.getElementById("accId").value = "";
    document.getElementById("accName").value = "";
    document.getElementById("accService").value = "";
    document.getElementById("accUsername").value = "";
    document.getElementById("accPassword").value = "";
    await loadAccountsData();
  } catch (err) {
    alert("Błąd: " + err);
  }
}

async function approveAction(actionId) {
  try {
    const res = await fetch(`/api/actions/${actionId}/approve`, { method: "POST" });
    if (res.ok) {
      alert("Akcja została zatwierdzona.");
      await loadAccountsData();
    } else {
      alert("Błąd zatwierdzania akcji");
    }
  } catch (e) {
    alert("Błąd: " + e);
  }
}

async function rejectAction(actionId) {
  try {
    const res = await fetch(`/api/actions/${actionId}/reject`, { method: "POST" });
    if (res.ok) {
      alert("Akcja została odrzucona.");
      await loadAccountsData();
    } else {
      alert("Błąd odrzucania akcji");
    }
  } catch (e) {
    alert("Błąd: " + e);
  }
}

async function submit2FACode(e, reqId) {
  e.preventDefault();
  const input = document.getElementById(`twofa_input_${reqId}`);
  const code = input.value.trim();
  if (!code) return;

  try {
    const res = await fetch(`/api/2fa/${reqId}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code })
    });
    if (res.ok) {
      alert("Kod 2FA został przekazany do agenta. Status konta: połączone.");
      await loadAccountsData();
    } else {
      alert("Błąd przesyłania kodu 2FA");
    }
  } catch (err) {
    alert("Błąd: " + err);
  }
}

// ---------------- BOT 3: WIDEO ----------------
async function loadVideoJobs(showLoader = true) {
  const container = document.getElementById("videoJobsList");
  try {
    const res = await fetch("/api/video/jobs?limit=15");
    const jobs = await res.json();
    if (!jobs.length) {
      container.innerHTML = `<div class="text-muted" style="padding:15px; text-align:center;">Brak zadań w kolejce. Wpisz prompt powyżej.</div>`;
      return;
    }

    container.innerHTML = jobs.map(j => {
      const p = j.payload || {};
      const statusBadgeClass = j.status === 'done' ? 'badge-status-running' : (j.status === 'running' ? 'badge-status-starting' : '');
      const downloadBtn = j.status === 'done'
        ? `<a href="/api/video/download/${j.id}" class="btn btn-sm btn-cyan" download>⬇ Pobierz MP4</a>`
        : '';

      return `
        <div class="video-job-card">
          <div class="video-job-header">
            <span class="video-job-id">#${j.id}</span>
            <span class="badge ${statusBadgeClass}">${j.status}</span>
            <span class="text-muted" style="font-size:0.75rem; margin-left:auto;">${j.created ? j.created.slice(11, 19) : ''}</span>
          </div>
          <div class="video-job-prompt">„${escapeHtml(p.prompt || '(brak promptu)')}”</div>
          <div class="video-job-meta">
            <span>Model: ${p.model || 'hf_ltx'}</span> • 
            <span>Format: ${p.aspect || '16:9'}</span> • 
            <span>Klipy: ${p.clips || 1} (${(p.clips || 1) * 4}s)</span>
          </div>
          ${downloadBtn ? `<div style="margin-top:10px;">${downloadBtn}</div>` : ''}
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Błąd pobierania zadań wideo:", e);
  }
}

async function submitVideoJob(e) {
  e.preventDefault();
  const prompt = document.getElementById("videoPrompt").value.trim();
  const model = document.getElementById("videoModel").value;
  const clips = parseInt(document.getElementById("videoClips").value, 10);
  const aspect = document.getElementById("videoAspect").value;
  const seed = parseInt(document.getElementById("videoSeed").value, 10);

  const btn = document.getElementById("btnGenerateVideo");
  btn.disabled = true;
  btn.textContent = "⏳ Dodawanie...";

  try {
    const res = await fetch("/api/video/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, model, clips, aspect, seed })
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Błąd: " + (data.detail || data.error));
    } else {
      document.getElementById("videoPrompt").value = "";
      await loadVideoJobs();
      alert(`Zadanie #${data.job_id} dodane do kolejki!`);
    }
  } catch (err) {
    alert("Błąd połączenia: " + err);
  } finally {
    btn.disabled = false;
    btn.textContent = "🚀 Dodaj do kolejki wideo";
  }
}

// ---------------- SEJF DANYCH DOSTĘPOWYCH ----------------
async function loadVault() {
  try {
    const res = await fetch("/api/vault");
    const names = await res.json();
    const listEl = document.getElementById("vaultNamesList");
    if (!names.length) {
      listEl.innerHTML = `<li class="text-muted">Sejf jest pusty.</li>`;
      return;
    }
    listEl.innerHTML = names.map(n => `
      <li>
        <span>🔑 <strong>${escapeHtml(n)}</strong></span>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteVaultItem('${n}')">Usuń</button>
      </li>
    `).join("");
  } catch (e) {
    console.error("Błąd sejfu:", e);
  }
}

async function deleteVaultItem(name) {
  if (!confirm(`Czy na pewno usunąć klucz '${name}' z sejfu?`)) return;
  try {
    await fetch(`/api/vault/${name}`, { method: "DELETE" });
    await loadVault();
    await checkVastStatus();
  } catch (e) {
    alert("Błąd usuwania: " + e);
  }
}

async function saveVaultSecret(e) {
  e.preventDefault();
  const name = document.getElementById("vaultSecretName").value.trim();
  const rawData = document.getElementById("vaultSecretData").value.trim();

  let parsed = {};
  try {
    parsed = JSON.parse(rawData);
  } catch (err) {
    alert("Dane muszą być poprawnym formatem JSON, np. {\"api_key\": \"...\"}");
    return;
  }

  try {
    const res = await fetch("/api/vault", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, data: parsed })
    });
    if (res.ok) {
      alert(`Pomyślnie zapisano pozycję '${name}' w sejfie!`);
      document.getElementById("vaultSecretName").value = "";
      document.getElementById("vaultSecretData").value = "";
      await loadVault();
      await checkVastStatus();
    } else {
      alert("Błąd zapisu w sejfie");
    }
  } catch (err) {
    alert("Błąd połączenia: " + err);
  }
}

// ---------------- KOLEJKA I HARMONOGRAM ----------------
async function loadJobsModalData() {
  try {
    const res = await fetch("/api/jobs");
    const data = await res.json();

    const schedEl = document.getElementById("schedJobsList");
    schedEl.innerHTML = `
      <table>
        <thead><tr><th>Bot</th><th>Nazwa zadania</th><th>Interwał</th></tr></thead>
        <tbody>
          ${(data.jobs || []).map(j => `<tr><td>${j.bot}</td><td>${j.name}</td><td>co ${j.every_h} h</td></tr>`).join("")}
        </tbody>
      </table>
    `;

    const logEl = document.getElementById("jobsLogList");
    logEl.innerHTML = `
      <table>
        <thead><tr><th>Bot</th><th>Zadanie</th><th>Status</th><th>Szczegóły</th><th>Czas</th></tr></thead>
        <tbody>
          ${(data.log || []).map(l => `<tr><td>${l.bot}</td><td>${l.job}</td><td>${l.status}</td><td>${escapeHtml(l.info || '')}</td><td>${l.created}</td></tr>`).join("")}
        </tbody>
      </table>
    `;
  } catch (e) {
    console.error("Błąd pobierania zadań:", e);
  }
}

// ---------------- MODALE UTILS ----------------
function openModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("active");
    if (id === "vaultModal") loadVault();
    if (id === "jobsModal") loadJobsModalData();
    if (id === "alertsModal") loadAlerts();
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
