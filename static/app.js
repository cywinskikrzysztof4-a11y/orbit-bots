// Orbit Bots — Client JavaScript (Vanilla JS, Zero Dependencies)

let currentBot = "flights";
let routesData = [];
let selectedRouteId = null;
let vastStatus = {};

document.addEventListener("DOMContentLoaded", () => {
  initApp();
  // Okresowe odświeżanie danych co 15 sekund
  setInterval(refreshPeriodicData, 15000);
});

async function initApp() {
  await Promise.all([
    checkVastStatus(),
    loadAlerts(),
    loadRoutes(),
    loadDeals(),
    loadChatHistory(),
    loadVideoJobs()
  ]);
}

function refreshPeriodicData() {
  checkVastStatus();
  loadAlerts();
  if (currentBot === "flights") {
    loadRoutes(false);
  } else if (currentBot === "video") {
    loadVideoJobs(false);
  }
}

// Przełączanie aktywnego bota
function switchBot(botId) {
  currentBot = botId;
  document.querySelectorAll(".bot-nav-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-bot") === botId);
  });
  document.querySelectorAll(".bot-view").forEach(view => {
    view.classList.toggle("active", view.id === `view-${botId}`);
  });
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
  try {
    const res = await fetch("/api/vast/start", { method: "POST" });
    const data = await res.json();
    if (!res.ok) alert("Błąd uruchomienia: " + (data.detail || data.error));
    await checkVastStatus();
  } catch (e) {
    alert("Błąd połączenia: " + e);
  }
}

async function stopVast() {
  if (!confirm("Czy na pewno chcesz zatrzymać instancję GPU Vast.ai?")) return;
  try {
    const res = await fetch("/api/vast/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) alert("Błąd zatrzymania: " + (data.detail || data.error));
    await checkVastStatus();
  } catch (e) {
    alert("Błąd połączenia: " + e);
  }
}

// ---------------- BOT 1: ŁOWCA LOTÓW ----------------
async function loadRoutes(showLoading = true) {
  const container = document.getElementById("routesList");
  if (showLoading && !routesData.length) {
    container.innerHTML = `<div class="loading-state">Ładowanie tras...</div>`;
  }
  try {
    const res = await fetch("/api/flights/routes");
    routesData = await res.json();
    document.getElementById("routesCount").textContent = `${routesData.length} tras`;

    if (!routesData.length) {
      container.innerHTML = `<div class="text-muted" style="padding:15px; text-align:center;">Brak zdefiniowanych tras. Kliknij "+ Dodaj trasę", aby monitorować np. WMI→BCN.</div>`;
      return;
    }

    container.innerHTML = routesData.map(r => {
      const bestPrice = r.history && r.history.length ? r.history[r.history.length - 1].min_price : null;
      const bestDate = r.history && r.history.length ? r.history[r.history.length - 1].min_date : "—";
      const curr = r.history && r.history.length ? r.history[r.history.length - 1].currency : "PLN";

      return `
        <div class="route-card ${selectedRouteId === r.id ? 'active' : ''}" onclick="selectRoute(${r.id})">
          <div class="route-meta">
            <div class="route-badges">
              <span class="iata-badge">${r.origin} ➔ ${r.dest}</span>
              <span class="route-month">${r.month} • ${r.provider}</span>
            </div>
          </div>
          <div style="display:flex; align-items:center;">
            <div class="route-pricing">
              <div class="route-price-main">${bestPrice ? `${bestPrice.toFixed(0)} ${curr}` : "brak danych"}</div>
              <div class="route-date-sub">Wylot: ${bestDate}</div>
            </div>
            <div class="route-actions" onclick="event.stopPropagation()">
              <button class="btn btn-sm btn-outline" title="Sprawdź teraz" onclick="checkRoute(${r.id})">⚡</button>
              <button class="btn btn-sm btn-cyan" title="Alert testowy" onclick="checkRoute(${r.id}, true)">🔔 Test</button>
              <button class="btn btn-sm btn-outline-danger" title="Usuń trasę" onclick="deleteRoute(${r.id})">✕</button>
            </div>
          </div>
        </div>
      `;
    }).join("");

    if (!selectedRouteId && routesData.length > 0) {
      selectRoute(routesData[0].id);
    } else if (selectedRouteId) {
      selectRoute(selectedRouteId);
    }
  } catch (e) {
    console.error("Błąd ładowania tras:", e);
  }
}

function selectRoute(id) {
  selectedRouteId = id;
  const route = routesData.find(r => r.id === id);
  if (!route) return;

  const chartCard = document.getElementById("chartCard");
  chartCard.style.display = "block";
  document.getElementById("chartTitle").textContent = `Historia cen: ${route.origin} ➔ ${route.dest} (${route.month})`;

  // Render wykresu historii
  renderSvgChart(route.history || []);
  // Render słupków dziennych
  renderDayBars(route.days || []);
}

function renderSvgChart(history) {
  const container = document.getElementById("svgChartContainer");
  if (!history || history.length < 2) {
    container.innerHTML = `<div class="text-muted" style="text-align:center; padding:50px;">Za mało pomiarów do narysowania linii (min. 2 sprawdzenia). Kliknij „⚡” przy trasie.</div>`;
    return;
  }

  const prices = history.map(h => h.min_price);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const range = (maxP - minP) || 1;

  const width = 600;
  const height = 160;
  const padX = 40;
  const padY = 25;

  const points = history.map((h, i) => {
    const x = padX + (i / (history.length - 1)) * (width - 2 * padX);
    const y = height - padY - ((h.min_price - minP) / range) * (height - 2 * padY);
    return { x, y, price: h.min_price, date: h.checked ? h.checked.slice(5, 16) : "" };
  });

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  const dotsSvg = points.map(p => `
    <circle class="chart-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4.5">
      <title>${p.price} PLN (${p.date})</title>
    </circle>
  `).join("");

  container.innerHTML = `
    <svg class="svg-price-chart" viewBox="0 0 ${width} ${height}">
      <!-- Linie siatki -->
      <line x1="${padX}" y1="${padY}" x2="${width - padX}" y2="${padY}" stroke="rgba(124,92,255,0.15)" stroke-dasharray="2,2"/>
      <line x1="${padX}" y1="${height - padY}" x2="${width - padX}" y2="${height - padY}" stroke="rgba(124,92,255,0.15)"/>
      <text x="5" y="${padY + 4}" fill="#94a3b8" font-size="10">${maxP.toFixed(0)} PLN</text>
      <text x="5" y="${height - padY + 4}" fill="#94a3b8" font-size="10">${minP.toFixed(0)} PLN</text>
      <!-- Linia cen -->
      <path class="chart-line" d="${pathD}"/>
      ${dotsSvg}
    </svg>
  `;
}

function renderDayBars(days) {
  const container = document.getElementById("dayBarsContainer");
  if (!days || !days.length) {
    container.innerHTML = `<div class="text-muted" style="width:100%; text-align:center; line-height:80px;">Brak danych dzień po dniu dla wybranego miesiąca.</div>`;
    return;
  }

  const prices = days.map(d => d.price);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const range = (maxP - minP) || 1;

  container.innerHTML = days.map(d => {
    const heightPct = Math.max(15, Math.round(((d.price - minP) / range) * 80 + 15));
    const dayNum = d.date.split("-")[2];
    const isMin = d.price === minP;

    return `
      <div class="day-bar-wrap" title="${d.date}: ${d.price} ${d.currency}">
        <div class="day-bar ${isMin ? 'min-deal' : ''}" style="height: ${heightPct}%; ${isMin ? 'background:#34d399;' : ''}"></div>
        <span class="day-bar-label">${dayNum}</span>
      </div>
    `;
  }).join("");
}

function showAddRouteModal() {
  openModal("addRouteModal");
}

async function submitNewRoute(e) {
  e.preventDefault();
  const origin = document.getElementById("newRouteOrigin").value;
  const dest = document.getElementById("newRouteDest").value.toUpperCase();
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
    alert("Błąd zapisu trasy: " + err);
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

// ---------------- BOT 2: DZIENNY (CHAT) ----------------
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
    console.error("Błąd historii:", e);
  }
}

async function sendChatMessage(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("chatInput");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  appendChatMessage("user", msg);

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
      appendChatMessage("assistant", "⚠️ Błąd: " + (data.detail || data.error));
    } else {
      appendChatMessage("assistant", data.answer || "Brak odpowiedzi");
    }
  } catch (err) {
    appendChatMessage("assistant", "⚠️ Błąd połączenia: " + err);
  } finally {
    btn.disabled = false;
  }
}

function quickAsk(text) {
  document.getElementById("chatInput").value = text;
  sendChatMessage();
}

function appendChatMessage(role, content) {
  const container = document.getElementById("chatMessages");
  const div = document.createElement("div");
  div.className = `msg-bubble ${role}`;
  div.innerHTML = `
    <div class="msg-author">${role === "user" ? "Ty" : "Dzienny"}</div>
    <div class="msg-text">${escapeHtml(content).replace(/\n/g, "<br>")}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
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
        <div class="msg-text">Pamięć sesji została wyczyszczona. Zaczynamy nową rozmowę!</div>
      </div>
    `;
  } catch (e) {
    alert("Błąd: " + e);
  }
}

// ---------------- BOT 3: WIDEO ----------------
async function submitVideoJob(e) {
  e.preventDefault();
  const prompt = document.getElementById("videoPrompt").value.trim();
  const model = document.getElementById("videoModel").value;
  const clips = parseInt(document.getElementById("videoClips").value);
  const aspect = document.getElementById("videoAspect").value;
  const seed = parseInt(document.getElementById("videoSeed").value);

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
      return;
    }
    alert(`Dodano zadanie wideo #${data.job_id} do kolejki!`);
    document.getElementById("videoPrompt").value = "";
    await loadVideoJobs();
  } catch (err) {
    alert("Błąd generowania: " + err);
  } finally {
    btn.disabled = false;
    btn.textContent = "🚀 Dodaj do kolejki wideo";
  }
}

async function loadVideoJobs(showLoading = true) {
  const container = document.getElementById("videoJobsList");
  try {
    const res = await fetch("/api/video/jobs");
    const jobs = await res.json();

    if (!jobs.length) {
      container.innerHTML = `<div class="text-muted" style="padding:15px; text-align:center;">Brak zadań wideo. Wprowadź prompt po lewej stronie, aby wygenerować pierwsze wideo.</div>`;
      return;
    }

    container.innerHTML = jobs.map(j => {
      const isDone = j.status === "done";
      const isError = j.status === "error";
      const statusBadge = isDone
        ? `<span class="badge badge-status-running">Zakończono</span>`
        : (isError ? `<span class="badge badge-status-error">Błąd</span>` : `<span class="badge badge-status-starting">W toku (${j.status})</span>`);

      return `
        <div class="video-job-card">
          <div class="video-job-header">
            <strong>Zadanie #${j.id} (${j.payload.model || 'wideo'})</strong>
            ${statusBadge}
          </div>
          <div class="video-job-prompt">"${escapeHtml(j.payload.prompt || '')}"</div>
          ${isDone ? `
            <video class="video-preview-player" controls preload="metadata">
              <source src="/api/video/download/${j.id}" type="video/mp4">
              Twoja przeglądarka nie obsługuje tagu wideo.
            </video>
            <div style="display:flex; justify-content:flex-end; margin-top:6px;">
              <a href="/api/video/download/${j.id}" download class="btn btn-sm btn-cyan">⬇ Pobierz MP4</a>
            </div>
          ` : ""}
          ${isError ? `<div class="text-danger" style="font-size:0.75rem; color:#f87171;">${escapeHtml(j.result?.error || 'Nieznany błąd')}</div>` : ""}
        </div>
      `;
    }).join("");
  } catch (e) {
    console.error("Błąd zadań wideo:", e);
  }
}

// ---------------- ALERTY ----------------
async function loadAlerts() {
  try {
    const res = await fetch("/api/alerts");
    const alerts = await res.json();
    const unread = alerts.filter(a => !a.read).length;

    document.getElementById("totalAlertsCount").textContent = unread;
    document.getElementById("badge-flights").textContent = alerts.filter(a => a.bot === "flights" && !a.read).length;
    document.getElementById("badge-daily").textContent = alerts.filter(a => a.bot === "daily" && !a.read).length;
    document.getElementById("badge-video").textContent = alerts.filter(a => a.bot === "video" && !a.read).length;

    const container = document.getElementById("alertsListContainer");
    if (!alerts.length) {
      container.innerHTML = `<div class="text-muted" style="padding:20px; text-align:center;">Brak zarejestrowanych alertów.</div>`;
      return;
    }

    container.innerHTML = alerts.map(a => `
      <div class="deal-item" style="border-left-color: ${a.read ? '#64748b' : 'var(--accent-cyan)'}; margin-bottom:8px;">
        <div style="font-weight:700; color:#fff;">${escapeHtml(a.title)}</div>
        <div style="font-size:0.8rem; color:#e2e8f0; margin:4px 0;">${escapeHtml(a.body || '').replace(/\n/g, '<br>')}</div>
        <div style="font-size:0.65rem; color:var(--text-muted);">${a.created} • [${a.bot}]</div>
      </div>
    `).join("");
  } catch (e) {
    console.error("Błąd alertów:", e);
  }
}

async function markAllAlertsRead() {
  try {
    await fetch("/api/alerts/read", { method: "POST" });
    await loadAlerts();
  } catch (e) {
    alert("Błąd: " + e);
  }
}

// ---------------- SEJF (VAULT) ----------------
async function loadVault() {
  try {
    const res = await fetch("/api/vault");
    const names = await res.json();
    const list = document.getElementById("vaultNamesList");
    if (!names.length) {
      list.innerHTML = `<li class="text-muted">Brak zapisanych pozycji w sejfie.</li>`;
      return;
    }
    list.innerHTML = names.map(n => `<li>🔑 <strong>${escapeHtml(n)}</strong> (zaszyfrowano Fernet)</li>`).join("");
  } catch (e) {
    console.error("Błąd sejfu:", e);
  }
}

async function saveVaultSecret(e) {
  e.preventDefault();
  const name = document.getElementById("vaultSecretName").value.trim();
  const rawData = document.getElementById("vaultSecretData").value.trim();
  let parsed;
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
