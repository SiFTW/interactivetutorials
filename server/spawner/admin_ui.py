"""Self-contained HTML/CSS/JS dashboard for live classroom server health & funder statistics.

Served at `GET /admin` by `mitchell-tutorial-spawner`. Uses zero external CDN
assets so it loads cleanly and instantaneously over Cloudflare Tunnel.
"""

from __future__ import annotations

import json


def render_admin_page(*, auth_required: bool) -> str:
    """Render the self-contained admin & statistics HTML page."""
    auth_js = "true" if auth_required else "false"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Mitchell Lab Tutorial Server — Live Status &amp; Usage Statistics</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card: #ffffff;
      --border: #e2e8f0;
      --text: #0f172a;
      --muted: #64748b;
      --blue: #1d4ed8;
      --blue-soft: #eff6ff;
      --teal: #0f766e;
      --amber: #d97706;
      --red: #dc2626;
      --green: #16a34a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }}
    header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
      color: #ffffff;
      padding: 1.1rem 1.5rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.8rem;
      box-shadow: 0 2px 10px rgba(15, 23, 42, 0.16);
    }}
    .brand h1 {{
      margin: 0;
      font-size: 1.2rem;
      font-weight: 700;
      letter-spacing: -0.01em;
    }}
    .brand p {{
      margin: 0.15rem 0 0;
      font-size: 0.82rem;
      color: #cbd5e1;
    }}
    .header-controls {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.25rem 0.65rem;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
      background: rgba(255,255,255,0.14);
      color: #f8fafc;
    }}
    .dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #4ade80;
    }}
    .dot.warn {{ background: #fbbf24; }}
    .dot.err {{ background: #f87171; }}
    .btn {{
      padding: 0.4rem 0.78rem;
      border-radius: 7px;
      border: 1px solid rgba(255,255,255,0.28);
      background: rgba(255,255,255,0.12);
      color: #ffffff;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
    }}
    .btn:hover {{ background: rgba(255,255,255,0.22); }}
    .btn-light {{
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--text);
    }}
    .btn-light:hover {{ background: var(--blue-soft); border-color: #93c5fd; color: var(--blue); }}
    .btn-light.active {{ background: var(--blue); border-color: var(--blue); color: #ffffff; }}
    .btn-danger {{
      border: 1px solid #fecaca;
      background: #fef2f2;
      color: #b91c1c;
      padding: 0.22rem 0.55rem;
      font-size: 0.76rem;
    }}
    .btn-danger:hover {{ background: #dc2626; color: #ffffff; border-color: #dc2626; }}

    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 1.25rem 1.25rem 3rem;
    }}
    .notice {{
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      color: #1e3a8a;
      border-radius: 10px;
      padding: 0.65rem 1rem;
      font-size: 0.84rem;
      margin-bottom: 1rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }}
    .notice.err {{ background: #fef2f2; border-color: #fecaca; color: #991b1b; }}
    .section-title {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.6rem;
      margin: 1.4rem 0 0.75rem;
    }}
    .section-title h2 {{
      margin: 0;
      font-size: 1rem;
      font-weight: 700;
      color: var(--text);
    }}
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(235px, 1fr));
      gap: 0.9rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.1rem;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }}
    .kpi-label {{
      font-size: 0.78rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    .kpi-val {{
      font-size: 1.75rem;
      font-weight: 800;
      margin: 0.25rem 0 0.15rem;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.02em;
    }}
    .kpi-sub {{
      font-size: 0.81rem;
      color: var(--muted);
    }}
    .bar-track {{
      height: 8px;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 0.55rem;
    }}
    .bar-fill {{
      height: 100%;
      border-radius: 999px;
      background: var(--blue);
      transition: width 0.35s ease;
    }}
    .bar-fill.ok {{ background: var(--green); }}
    .bar-fill.warn {{ background: var(--amber); }}
    .bar-fill.hot {{ background: var(--red); }}

    .table-wrap {{
      overflow-x: auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }}
    th, td {{
      padding: 0.62rem 0.8rem;
      text-align: left;
      border-bottom: 1px solid #f1f5f9;
      white-space: nowrap;
    }}
    th {{
      background: #f8fafc;
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: none; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }}
    .mini-bar {{
      display: inline-block;
      width: 58px;
      height: 7px;
      background: #e2e8f0;
      border-radius: 999px;
      overflow: hidden;
      vertical-align: middle;
      margin-right: 6px;
    }}
    .mini-bar > span {{ display: block; height: 100%; background: var(--blue); }}
    .empty-row {{
      text-align: center;
      color: var(--muted);
      padding: 1.4rem !important;
      font-style: italic;
    }}

    .chart-box {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.9rem 1rem 0.6rem;
    }}
    .chart-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      font-size: 0.79rem;
      color: var(--muted);
      margin-bottom: 0.4rem;
    }}
    .swatch {{
      display: inline-block;
      width: 11px;
      height: 11px;
      border-radius: 3px;
      vertical-align: middle;
      margin-right: 4px;
    }}

    .auth-overlay {{
      max-width: 440px;
      margin: 4rem auto;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.6rem;
      box-shadow: 0 8px 28px rgba(15, 23, 42, 0.08);
    }}
    .auth-overlay h2 {{ margin-top: 0; font-size: 1.15rem; }}
    .auth-overlay input {{
      width: 100%;
      padding: 0.6rem 0.75rem;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 0.92rem;
      margin: 0.6rem 0 0.85rem;
    }}
    .auth-overlay button {{
      width: 100%;
      padding: 0.6rem;
      border-radius: 8px;
      border: none;
      background: var(--blue);
      color: #ffffff;
      font-weight: 700;
      font-size: 0.92rem;
      cursor: pointer;
    }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>Mitchell Lab Tutorial Server — Live Status &amp; Impact</h1>
      <p>Real-time classroom container monitor &amp; persistent usage statistics</p>
    </div>
    <div class="header-controls">
      <span class="pill" id="liveBadge"><span class="dot" id="liveDot"></span><span id="liveText">Connecting…</span></span>
      <button class="btn" id="toggleAutoBtn" type="button">⏸ Pause (5s)</button>
      <button class="btn" id="refreshBtn" type="button">🔄 Refresh</button>
      <button class="btn hidden" id="logoutBtn" type="button">🔒 Lock</button>
    </div>
  </header>

  <main>
    <div id="authBox" class="auth-overlay hidden">
      <h2>Admin Token Required</h2>
      <p style="font-size:0.86rem;color:#475569;margin-top:0;">
        Enter the <code>ADMIN_TOKEN</code> configured in <code>server/.env</code> on your tutorial server.
      </p>
      <form id="authForm">
        <input id="tokenInput" type="password" placeholder="Paste ADMIN_TOKEN…" autocomplete="current-password" required />
        <button type="submit">Unlock Dashboard</button>
      </form>
      <p id="authErr" style="color:#dc2626;font-size:0.82rem;margin:0.6rem 0 0;"></p>
    </div>

    <div id="dashboard" class="hidden">
      <div id="banner" class="notice hidden"></div>

      <div class="section-title" style="margin-top:0.2rem;">
        <h2>Live Server &amp; Classroom Health</h2>
        <span style="font-size:0.8rem;color:#64748b;" id="lastUpdated">—</span>
      </div>
      <div class="grid-4">
        <div class="card">
          <div class="kpi-label">Active Student Containers</div>
          <div class="kpi-val" id="kpiSessions">—</div>
          <div class="kpi-sub" id="kpiSessionsSub">—</div>
          <div class="bar-track"><div class="bar-fill" id="barSessions" style="width:0%"></div></div>
        </div>
        <div class="card">
          <div class="kpi-label">Host CPU Utilization</div>
          <div class="kpi-val" id="kpiCpu">—</div>
          <div class="kpi-sub" id="kpiCpuSub">—</div>
          <div class="bar-track"><div class="bar-fill" id="barCpu" style="width:0%"></div></div>
        </div>
        <div class="card">
          <div class="kpi-label">Host Memory (RAM)</div>
          <div class="kpi-val" id="kpiRam">—</div>
          <div class="kpi-sub" id="kpiRamSub">—</div>
          <div class="bar-track"><div class="bar-fill" id="barRam" style="width:0%"></div></div>
        </div>
        <div class="card">
          <div class="kpi-label">Deployed Kernel Image</div>
          <div class="kpi-val mono" id="kpiSha" style="font-size:1.35rem;margin-top:0.45rem;">—</div>
          <div class="kpi-sub" id="kpiImgSub">—</div>
        </div>
      </div>

      <div class="section-title">
        <h2>Impact &amp; Funder Usage Statistics</h2>
        <div style="display:flex;flex-wrap:wrap;gap:0.4rem;align-items:center;">
          <button class="btn btn-light active" data-window="all_time">All-Time</button>
          <button class="btn btn-light" data-window="last_30d">30 Days</button>
          <button class="btn btn-light" data-window="last_7d">7 Days</button>
          <button class="btn btn-light" data-window="last_24h">24 Hours</button>
          <button class="btn btn-light" id="exportCsvBtn" type="button">⬇ Export Funder CSV</button>
          <button class="btn btn-light" id="exportJsonBtn" type="button">⬇ Download JSON</button>
        </div>
      </div>
      <div class="grid-4">
        <div class="card">
          <div class="kpi-label">Total Instances Launched</div>
          <div class="kpi-val" id="statSessions">—</div>
          <div class="kpi-sub" id="statVisitors">—</div>
        </div>
        <div class="card">
          <div class="kpi-label">Peak Concurrent Users</div>
          <div class="kpi-val" id="statPeak">—</div>
          <div class="kpi-sub" id="statPeakAt">—</div>
        </div>
        <div class="card">
          <div class="kpi-label">Collective CPU-Hours</div>
          <div class="kpi-val" id="statCpuHrs">—</div>
          <div class="kpi-sub" id="statPeakMem">—</div>
        </div>
        <div class="card">
          <div class="kpi-label">Student Session-Hours</div>
          <div class="kpi-val" id="statSessHrs">—</div>
          <div class="kpi-sub" id="statAvgDur">—</div>
        </div>
      </div>

      <div class="section-title">
        <h2>Server Load &amp; Concurrent Users Over Time</h2>
        <div style="display:flex;gap:0.4rem;">
          <button class="btn btn-light active" data-hours="24">Last 24h</button>
          <button class="btn btn-light" data-hours="168">Last 7d</button>
          <button class="btn btn-light" data-hours="720">Last 30d</button>
        </div>
      </div>
      <div class="chart-box">
        <div class="chart-legend">
          <span><span class="swatch" style="background:#1d4ed8;"></span>Host CPU %</span>
          <span><span class="swatch" style="background:#0f766e;"></span>Host RAM %</span>
          <span><span class="swatch" style="background:#ea580c;"></span>Active Containers (right axis)</span>
        </div>
        <div id="chartWrap" style="width:100%;min-height:190px;"></div>
      </div>

      <div class="section-title">
        <h2>Active Student Containers (<span id="activeCountHdr">0</span>)</h2>
        <span style="font-size:0.8rem;color:#64748b;" id="containersTotalSub">—</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Visitor</th>
              <th>Age</th>
              <th>Idle</th>
              <th>WS</th>
              <th>CPU (% of 1 core)</th>
              <th>% Host CPU</th>
              <th>RAM Used / Limit</th>
              <th>% Host RAM</th>
              <th>PIDs</th>
              <th>CPU-sec</th>
              <th id="actionColHdr" class="hidden">Action</th>
            </tr>
          </thead>
          <tbody id="activeBody">
            <tr><td colspan="12" class="empty-row">Loading…</td></tr>
          </tbody>
        </table>
      </div>

      <div class="section-title">
        <h2>Recent Completed Sessions</h2>
        <span style="font-size:0.8rem;color:#64748b;">Anonymized · zero raw IPs or session tokens stored</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Visitor</th>
              <th>Started (UTC)</th>
              <th>Duration</th>
              <th>CPU-sec</th>
              <th>Peak RAM</th>
              <th>End Reason</th>
            </tr>
          </thead>
          <tbody id="recentBody">
            <tr><td colspan="7" class="empty-row">No completed sessions recorded yet.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <script>
    const AUTH_REQUIRED = {auth_js};
    const TOKEN_KEY = "mitchell-admin-token";
    let adminToken = window.sessionStorage.getItem(TOKEN_KEY) || "";
    let selectedWindow = "all_time";
    let selectedHours = 24;
    let autoRefresh = true;
    let refreshTimer = null;
    let latestData = null;

    function fmtDuration(sec) {{
      sec = Math.max(0, Math.round(sec || 0));
      if (sec < 60) return sec + "s";
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      if (m < 60) return m + "m " + s + "s";
      const h = Math.floor(m / 60);
      return h + "h " + (m % 60) + "m";
    }}

    function barClass(pct) {{
      if (pct >= 85) return "bar-fill hot";
      if (pct >= 60) return "bar-fill warn";
      return "bar-fill ok";
    }}

    function authHeaders() {{
      return adminToken ? {{ Authorization: "Bearer " + adminToken }} : {{}};
    }}

    function showAuth(msg) {{
      document.getElementById("dashboard").classList.add("hidden");
      document.getElementById("authBox").classList.remove("hidden");
      document.getElementById("logoutBtn").classList.add("hidden");
      document.getElementById("authErr").textContent = msg || "";
      document.getElementById("liveDot").className = "dot warn";
      document.getElementById("liveText").textContent = "Locked";
    }}

    function showDashboard() {{
      document.getElementById("authBox").classList.add("hidden");
      document.getElementById("dashboard").classList.remove("hidden");
      if (AUTH_REQUIRED) {{
        document.getElementById("logoutBtn").classList.remove("hidden");
      }}
    }}

    function renderSummary() {{
      if (!latestData || !latestData.summary) return;
      const s = latestData.summary;
      const w = s[selectedWindow] || s.all_time;
      document.getElementById("statSessions").textContent = w.sessions.toLocaleString();
      document.getElementById("statVisitors").textContent =
        w.unique_visitors.toLocaleString() + " unique anonymized visitors";
      document.getElementById("statPeak").textContent = s.peak_concurrent_users.toLocaleString();
      document.getElementById("statPeakAt").textContent = s.peak_concurrent_at
        ? "Recorded " + s.peak_concurrent_at.replace("T", " ").replace("Z", " UTC")
        : "Since " + (s.first_recorded_at || "startup");
      document.getElementById("statCpuHrs").textContent = w.cpu_hours.toFixed(2) + " h";
      document.getElementById("statPeakMem").textContent =
        "Peak single container RAM: " + w.peak_container_mem_mb.toFixed(0) + " MiB";
      document.getElementById("statSessHrs").textContent = w.session_hours.toFixed(1) + " h";
      document.getElementById("statAvgDur").textContent =
        "Avg session: " + w.avg_duration_minutes.toFixed(1) + " min";
    }}

    function renderChart(points) {{
      const wrap = document.getElementById("chartWrap");
      if (!points || points.length < 2) {{
        wrap.innerHTML =
          '<p style="text-align:center;color:#64748b;padding:2.5rem 0;font-size:0.85rem;">' +
          'Collecting time-series snapshots (1 sample / minute) — chart will appear after 2 samples.</p>';
        return;
      }}
      const W = 960, H = 200, padL = 42, padR = 42, padT = 14, padB = 28;
      const plotW = W - padL - padR, plotH = H - padT - padB;
      const tMin = points[0].ts, tMax = Math.max(tMin + 1, points[points.length - 1].ts);
      const maxUsers = Math.max(4, ...points.map(p => p.active_sessions));

      const xOf = (ts) => padL + ((ts - tMin) / (tMax - tMin)) * plotW;
      const yPct = (v) => padT + plotH - (Math.min(100, Math.max(0, v)) / 100) * plotH;
      const yUsr = (v) => padT + plotH - (v / maxUsers) * plotH;

      const poly = (fn) => points.map(p => xOf(p.ts).toFixed(1) + "," + fn(p).toFixed(1)).join(" ");

      const gridLines = [0, 25, 50, 75, 100].map(pct => {{
        const y = yPct(pct).toFixed(1);
        return `<line x1="${{padL}}" y1="${{y}}" x2="${{W - padR}}" y2="${{y}}" stroke="#f1f5f9" stroke-width="1"/>` +
               `<text x="${{padL - 6}}" y="${{Number(y) + 3}}" text-anchor="end" font-size="10" fill="#64748b">${{pct}}%</text>`;
      }}).join("");

      const rightTicks = [0, Math.round(maxUsers / 2), maxUsers].map(u => {{
        const y = yUsr(u).toFixed(1);
        return `<text x="${{W - padR + 6}}" y="${{Number(y) + 3}}" text-anchor="start" font-size="10" fill="#ea580c">${{u}}</text>`;
      }}).join("");

      const tStartLbl = (points[0].iso || "").slice(5, 16).replace("T", " ");
      const tEndLbl = (points[points.length - 1].iso || "").slice(5, 16).replace("T", " ");

      wrap.innerHTML = `
        <svg viewBox="0 0 ${{W}} ${{H}}" style="width:100%;height:auto;display:block;">
          ${{gridLines}}
          ${{rightTicks}}
          <polyline fill="none" stroke="#1d4ed8" stroke-width="2" points="${{poly(p => yPct(p.host_cpu_pct))}}" />
          <polyline fill="none" stroke="#0f766e" stroke-width="2" points="${{poly(p => yPct(p.host_mem_pct))}}" />
          <polyline fill="none" stroke="#ea580c" stroke-width="2.4" points="${{poly(p => yUsr(p.active_sessions))}}" />
          <text x="${{padL}}" y="${{H - 6}}" font-size="10" fill="#64748b">${{tStartLbl}} UTC</text>
          <text x="${{W - padR}}" y="${{H - 6}}" text-anchor="end" font-size="10" fill="#64748b">${{tEndLbl}} UTC</text>
        </svg>`;
    }}

    function renderData(data) {{
      latestData = data;
      showDashboard();

      const h = data.host || {{}};
      const srv = data.server || {{}};
      const containers = data.containers || [];
      const canManage = Boolean(data.can_manage);

      // Banner note when read-only
      const banner = document.getElementById("banner");
      if (!AUTH_REQUIRED) {{
        banner.className = "notice";
        banner.innerHTML =
          '<span><strong>Read-only monitoring mode.</strong> Set <code>ADMIN_TOKEN</code> in <code>server/.env</code> to password-protect this page and enable the <em>Stop Container</em> button.</span>';
      }} else {{
        banner.className = "notice hidden";
      }}

      // Live KPIs
      const active = srv.active_sessions || 0;
      const maxS = srv.max_sessions || 1;
      const sessPct = Math.min(100, (100 * active) / maxS);
      document.getElementById("kpiSessions").textContent = active + " / " + maxS;
      document.getElementById("kpiSessionsSub").textContent =
        "Limits: " + (srv.container_cpus || 2) + " cores & " + (srv.container_mem_limit || "2g") + " RAM per user";
      const barS = document.getElementById("barSessions");
      barS.style.width = sessPct.toFixed(1) + "%";
      barS.className = barClass(sessPct);

      const totContCpu = containers.reduce((a, c) => a + (c.cpu_percent || 0), 0);
      const totContMemMb = containers.reduce((a, c) => a + (c.mem_mb || 0), 0);
      const hostCores = h.cpu_cores || 1;
      const contHostCpuPct = (totContCpu / hostCores);

      document.getElementById("kpiCpu").textContent = (h.cpu_percent ?? 0).toFixed(1) + "%";
      document.getElementById("kpiCpuSub").textContent =
        hostCores + " cores · Load " + h.load_avg_1m + " / " + h.load_avg_5m + " / " + h.load_avg_15m +
        " · Tutorials: " + contHostCpuPct.toFixed(1) + "%";
      const barC = document.getElementById("barCpu");
      barC.style.width = Math.min(100, h.cpu_percent || 0).toFixed(1) + "%";
      barC.className = barClass(h.cpu_percent || 0);

      document.getElementById("kpiRam").textContent =
        (h.mem_used_gb ?? 0).toFixed(1) + " / " + (h.mem_total_gb ?? 0).toFixed(1) + " GB";
      document.getElementById("kpiRamSub").textContent =
        (h.mem_percent ?? 0).toFixed(1) + "% used · Tutorials: " + (totContMemMb / 1024).toFixed(2) + " GB";
      const barR = document.getElementById("barRam");
      barR.style.width = Math.min(100, h.mem_percent || 0).toFixed(1) + "%";
      barR.className = barClass(h.mem_percent || 0);

      const sha = srv.kernel_git_sha || "unknown";
      const shortSha = sha.length > 7 ? sha.slice(0, 7) : sha;
      document.getElementById("kpiSha").innerHTML =
        sha !== "unknown"
          ? `<a href="https://github.com/SiFTW/interactivetutorials/commit/${{sha}}" target="_blank" rel="noopener" style="color:#1d4ed8;text-decoration:none;">${{shortSha}} ↗</a>`
          : "unknown";
      const builtAt = (srv.kernel_image_created || "").slice(0, 19).replace("T", " ");
      document.getElementById("kpiImgSub").textContent =
        "Built " + (builtAt || "unknown") + " UTC · Up " + fmtDuration(srv.uptime_seconds || 0);

      renderSummary();
      renderChart(data.timeseries || []);

      // Active containers table
      document.getElementById("activeCountHdr").textContent = String(containers.length);
      document.getElementById("containersTotalSub").textContent =
        "Combined tutorial usage: " + totContCpu.toFixed(1) + "% CPU (" + contHostCpuPct.toFixed(1) +
        "% of host) · " + totContMemMb.toFixed(0) + " MiB RAM";
      document.getElementById("actionColHdr").classList.toggle("hidden", !canManage);

      const activeBody = document.getElementById("activeBody");
      if (containers.length === 0) {{
        activeBody.innerHTML =
          `<tr><td colspan="${{canManage ? 12 : 11}}" class="empty-row">No active student containers right now.</td></tr>`;
      }} else {{
        activeBody.innerHTML = containers.map(c => {{
          const cpuCapPct = Math.min(100, (c.cpu_percent / ((srv.container_cpus || 2) * 100)) * 100);
          const memBarPct = Math.min(100, c.mem_percent || 0);
          const hostCpuShare = (c.cpu_percent / hostCores).toFixed(1) + "%";
          const hostRamShare = h.mem_total_bytes > 0
            ? ((c.mem_bytes / h.mem_total_bytes) * 100).toFixed(1) + "%"
            : "—";
          const actTd = canManage
            ? `<td><button class="btn btn-danger" onclick="stopSession('${{c.session_id}}')">Stop</button></td>`
            : "";
          return `<tr>
            <td class="mono">${{c.session_id.slice(0, 8)}}</td>
            <td class="mono">${{c.visitor_id}}</td>
            <td>${{fmtDuration(c.age_seconds)}}</td>
            <td>${{fmtDuration(c.idle_seconds)}}</td>
            <td>${{c.active_ws}}</td>
            <td><span class="mini-bar"><span style="width:${{cpuCapPct.toFixed(0)}}%"></span></span>${{c.cpu_percent.toFixed(1)}}%</td>
            <td>${{hostCpuShare}}</td>
            <td><span class="mini-bar"><span style="width:${{memBarPct.toFixed(0)}}%;background:${{memBarPct > 80 ? '#dc2626' : '#0f766e'}}"></span></span>${{c.mem_mb.toFixed(0)}} / ${{c.mem_limit_mb.toFixed(0)}} MiB</td>
            <td>${{hostRamShare}}</td>
            <td>${{c.pids}} / ${{srv.container_pids_limit || 256}}</td>
            <td class="mono">${{c.cpu_seconds.toFixed(1)}}s</td>
            ${{actTd}}
          </tr>`;
        }}).join("");
      }}

      // Recent completed sessions
      const recent = data.recent_sessions || [];
      const recentBody = document.getElementById("recentBody");
      if (recent.length === 0) {{
        recentBody.innerHTML = '<tr><td colspan="7" class="empty-row">No completed sessions recorded yet.</td></tr>';
      }} else {{
        recentBody.innerHTML = recent.map(r => `<tr>
          <td class="mono">${{r.session_id}}</td>
          <td class="mono">${{r.visitor_id}}</td>
          <td class="mono">${{(r.started_at || "").replace("T", " ").replace("Z", "")}}</td>
          <td>${{fmtDuration(r.duration_seconds)}}</td>
          <td class="mono">${{r.cpu_seconds.toFixed(1)}}s</td>
          <td>${{r.peak_mem_mb.toFixed(0)}} MiB</td>
          <td>${{r.end_reason || "—"}}</td>
        </tr>`).join("");
      }}

      document.getElementById("liveDot").className = "dot";
      document.getElementById("liveText").textContent = "Live";
      document.getElementById("lastUpdated").textContent =
        "Updated " + new Date().toLocaleTimeString();
    }}

    async function fetchStats() {{
      if (AUTH_REQUIRED && !adminToken) {{
        showAuth("");
        return;
      }}
      try {{
        const resp = await fetch("/api/admin/stats?hours=" + selectedHours, {{
          headers: authHeaders(),
        }});
        if (resp.status === 401 || resp.status === 403) {{
          adminToken = "";
          window.sessionStorage.removeItem(TOKEN_KEY);
          showAuth("Invalid or expired ADMIN_TOKEN. Please try again.");
          return;
        }}
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        renderData(data);
      }} catch (err) {{
        document.getElementById("liveDot").className = "dot err";
        document.getElementById("liveText").textContent = "Error";
        const banner = document.getElementById("banner");
        banner.className = "notice err";
        banner.textContent = "Failed to refresh server stats: " + err.message;
      }}
    }}

    async function stopSession(sid) {{
      if (!confirm("Stop active student container " + sid.slice(0, 8) + "?")) return;
      const resp = await fetch("/api/admin/sessions/" + encodeURIComponent(sid) + "/stop", {{
        method: "POST",
        headers: authHeaders(),
      }});
      if (!resp.ok) {{
        alert("Could not stop container (HTTP " + resp.status + ")");
      }}
      await fetchStats();
    }}

    async function downloadExport(path, filename) {{
      const resp = await fetch(path, {{ headers: authHeaders() }});
      if (!resp.ok) {{
        alert("Export failed (HTTP " + resp.status + ")");
        return;
      }}
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }}

    document.getElementById("authForm").addEventListener("submit", (evt) => {{
      evt.preventDefault();
      adminToken = document.getElementById("tokenInput").value.trim();
      window.sessionStorage.setItem(TOKEN_KEY, adminToken);
      document.getElementById("tokenInput").value = "";
      fetchStats();
    }});

    document.getElementById("logoutBtn").addEventListener("click", () => {{
      adminToken = "";
      window.sessionStorage.removeItem(TOKEN_KEY);
      showAuth("");
    }});

    document.getElementById("refreshBtn").addEventListener("click", fetchStats);
    document.getElementById("toggleAutoBtn").addEventListener("click", (evt) => {{
      autoRefresh = !autoRefresh;
      evt.target.textContent = autoRefresh ? "⏸ Pause (5s)" : "▶ Resume (5s)";
    }});

    document.querySelectorAll("[data-window]").forEach(btn => {{
      btn.addEventListener("click", () => {{
        selectedWindow = btn.getAttribute("data-window");
        document.querySelectorAll("[data-window]").forEach(b => b.classList.toggle("active", b === btn));
        renderSummary();
      }});
    }});

    document.querySelectorAll("[data-hours]").forEach(btn => {{
      btn.addEventListener("click", () => {{
        selectedHours = parseInt(btn.getAttribute("data-hours"), 10) || 24;
        document.querySelectorAll("[data-hours]").forEach(b => b.classList.toggle("active", b === btn));
        fetchStats();
      }});
    }});

    document.getElementById("exportCsvBtn").addEventListener("click", () => {{
      downloadExport("/api/admin/export.csv", "mitchell-lab-tutorials-usage-report.csv");
    }});
    document.getElementById("exportJsonBtn").addEventListener("click", () => {{
      downloadExport("/api/admin/stats?hours=" + selectedHours, "mitchell-lab-tutorials-stats.json");
    }});

    fetchStats();
    refreshTimer = setInterval(() => {{
      if (autoRefresh && (!AUTH_REQUIRED || adminToken)) fetchStats();
    }}, 5000);
  </script>
</body>
</html>"""
