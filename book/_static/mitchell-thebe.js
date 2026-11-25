/**
 * Mitchell Lab Interactive Tutorials — Live Editable Julia Cells via Thebe 0.9
 *
 * Connects every code cell in Jupyter Book 1 directly to our isolated per-user
 * Docker Binder-API spawner at https://kernels.mitchell.science, transforming
 * static code blocks into live, editable CodeMirror editors backed by Julia.
 */
(function () {
  const THEBE_VERSION = "0.9.2";
  const THEBE_JS_URL = `https://unpkg.com/thebe@${THEBE_VERSION}/lib/index.js`;
  const THEBE_CSS_URL = `https://unpkg.com/thebe@${THEBE_VERSION}/lib/thebe.css`;
  const STORAGE_PREFIX = "mitchell-thebe-binder";

  const BINDER_CONFIG = {
    repo: "SiFTW/interactivetutorials",
    ref: "main",
    binderUrl: "https://kernels.mitchell.science",
    repoProvider: "github",
  };

  const IMAGE_ID_KEY = "mitchell-thebe-kernel-image-id";

  // Crisp monochrome currentColor icons (automatically match button text & dark/light themes)
  const SVG_ATTR =
    'class="mitchell-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="display:inline-block;vertical-align:-2px;flex-shrink:0;"';
  const SPIN_ATTR =
    'class="mitchell-icon mitchell-icon-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="display:inline-block;vertical-align:-2px;flex-shrink:0;"';
  const ICONS = {
    play: `<svg ${SVG_ATTR}><polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none"/></svg>`,
    reset: `<svg ${SVG_ATTR}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><polyline points="3 3 3 8 8 8"/></svg>`,
    check: `<svg ${SVG_ATTR}><polyline points="20 6 9 17 4 12"/></svg>`,
    spinner: `<svg ${SPIN_ATTR}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>`,
  };

  let activating = false;
  let activated = false;
  let activeSessionCreds = null;

  function runWhenReady(cb) {
    if (document.readyState !== "loading") {
      cb();
    } else {
      document.addEventListener("DOMContentLoaded", cb);
    }
  }

  function parseSessionTarget(rawUrl, token) {
    if (!rawUrl || !token) return null;
    try {
      const parsed = new URL(rawUrl, BINDER_CONFIG.binderUrl);
      const match = parsed.pathname.match(/\/user\/([a-zA-Z0-9_-]+)/);
      if (!match) return null;
      return {
        origin: parsed.origin,
        sid: match[1],
        token: String(token),
      };
    } catch (_err) {
      return null;
    }
  }

  function collectSavedSessions(extraCreds) {
    const seen = new Set();
    const targets = [];
    const addTarget = (rawUrl, token) => {
      const t = parseSessionTarget(rawUrl, token);
      if (!t || seen.has(t.sid)) return;
      seen.add(t.sid);
      targets.push(t);
    };
    if (extraCreds && extraCreds.baseUrl && extraCreds.token) {
      addTarget(extraCreds.baseUrl, extraCreds.token);
    }
    try {
      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key && (key.startsWith(STORAGE_PREFIX) || key.startsWith("thebe-binder"))) {
          const raw = window.localStorage.getItem(key);
          if (!raw) continue;
          const data = JSON.parse(raw);
          if (data && (data.url || data.wsUrl) && data.token) {
            addTarget(data.url || data.wsUrl, data.token);
          }
        }
      }
    } catch (_err) {
      // Ignore storage restrictions
    }
    return targets;
  }

  async function stopSavedSessions(extraCreds) {
    const targets = collectSavedSessions(extraCreds || activeSessionCreds);
    if (targets.length === 0) return;
    await Promise.all(
      targets.map(async (t) => {
        const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
        const timer = ctrl ? setTimeout(() => ctrl.abort(), 2000) : null;
        try {
          const stopUrl = `${t.origin}/api/sessions/${encodeURIComponent(t.sid)}/stop?token=${encodeURIComponent(t.token)}`;
          await fetch(stopUrl, {
            method: "POST",
            keepalive: true,
            signal: ctrl ? ctrl.signal : undefined,
          });
        } catch (_err) {
          // Best-effort cleanup; ignore network errors during reset
        } finally {
          if (timer) clearTimeout(timer);
        }
      })
    );
  }

  async function fetchServerImageId() {
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), 2500) : null;
    try {
      const resp = await fetch(`${BINDER_CONFIG.binderUrl}/health`, {
        cache: "no-store",
        signal: ctrl ? ctrl.signal : undefined,
      });
      if (!resp.ok) return "";
      const data = await resp.json();
      return (data && (data.kernel_image_id || data.kernel_git_sha)) || "";
    } catch (_err) {
      return "";
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  function hasSavedSession() {
    try {
      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key && key.startsWith(STORAGE_PREFIX)) {
          return true;
        }
      }
    } catch (_) {
      // Ignore storage restrictions
    }
    return false;
  }

  function clearSavedSessions() {
    try {
      const toRemove = [];
      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (
          key &&
          (key.startsWith(STORAGE_PREFIX) ||
            key.startsWith("thebe-binder") ||
            key === IMAGE_ID_KEY)
        ) {
          toRemove.push(key);
        }
      }
      toRemove.forEach((k) => window.localStorage.removeItem(k));
    } catch (_) {
      // Ignore storage restrictions
    }
  }

  function loadStylesheet(href) {
    if (document.querySelector(`link[href="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (window.thebe) {
        resolve();
        return;
      }
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", (err) => reject(err));
        return;
      }
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = (err) => reject(err);
      document.head.appendChild(script);
    });
  }

  /**
   * Reliable sidebar toggle for both primary (left) and secondary (right)
   * sidebars across all viewport widths (desktop collapse + narrow slide-over drawer).
   */
  function wireSidebarToggles() {
    const htmlEl = document.documentElement;
    const primarySel =
      ".primary-toggle, [aria-label='Toggle primary sidebar'], [title='Toggle primary sidebar'], [data-bs-original-title='Toggle primary sidebar'], label[for='__primary'], label[for='pst-primary-sidebar-checkbox']";
    const secondarySel =
      ".secondary-toggle, [aria-label='Toggle secondary sidebar'], [title='Toggle secondary sidebar'], [data-bs-original-title='Toggle secondary sidebar'], label[for='__secondary'], label[for='pst-secondary-sidebar-checkbox']";

    let backdrop = document.querySelector(".mitchell-drawer-backdrop");
    if (!backdrop && document.body) {
      backdrop = document.createElement("div");
      backdrop.className = "mitchell-drawer-backdrop";
      backdrop.setAttribute("aria-hidden", "true");
      document.body.appendChild(backdrop);
    }

    function ensureSidebarHasContent(sidebarSel, modalId) {
      const sidebar = document.querySelector(sidebarSel);
      const modal = document.getElementById(modalId);
      if (sidebar && modal && sidebar.children.length === 0 && modal.children.length > 0) {
        while (modal.firstChild) sidebar.appendChild(modal.firstChild);
      }
      if (modal && typeof modal.close === "function" && modal.open) {
        modal.close();
      }
    }

    function closeMobileDrawers() {
      htmlEl.classList.remove("mitchell-show-primary-mobile", "mitchell-show-secondary-mobile");
    }

    document.addEventListener(
      "click",
      (evt) => {
        const targetEl = evt.target instanceof Element ? evt.target : evt.target.parentElement;
        if (!targetEl) return;

        if (targetEl.closest(primarySel)) {
          evt.preventDefault();
          evt.stopImmediatePropagation();
          if (window.matchMedia("(min-width: 992px)").matches) {
            htmlEl.classList.toggle("mitchell-hide-primary-sidebar");
          } else {
            ensureSidebarHasContent(".bd-sidebar-primary, #pst-primary-sidebar", "pst-primary-sidebar-modal");
            htmlEl.classList.remove("mitchell-show-secondary-mobile");
            htmlEl.classList.toggle("mitchell-show-primary-mobile");
          }
          return;
        }

        if (targetEl.closest(secondarySel)) {
          evt.preventDefault();
          evt.stopImmediatePropagation();
          if (window.matchMedia("(min-width: 1200px)").matches) {
            htmlEl.classList.toggle("mitchell-hide-secondary-sidebar");
          } else {
            ensureSidebarHasContent(".bd-sidebar-secondary, #pst-secondary-sidebar", "pst-secondary-sidebar-modal");
            htmlEl.classList.remove("mitchell-show-primary-mobile");
            htmlEl.classList.toggle("mitchell-show-secondary-mobile");
          }
          return;
        }

        // Auto-close right-hand ToC drawer after picking an in-page section link
        if (
          htmlEl.classList.contains("mitchell-show-secondary-mobile") &&
          targetEl.closest(".bd-sidebar-secondary a[href^='#'], #pst-secondary-sidebar a[href^='#']")
        ) {
          htmlEl.classList.remove("mitchell-show-secondary-mobile");
          return;
        }

        // Click outside an open mobile drawer (or on backdrop) closes it
        if (
          htmlEl.classList.contains("mitchell-show-primary-mobile") &&
          !targetEl.closest(".bd-sidebar-primary, #pst-primary-sidebar")
        ) {
          htmlEl.classList.remove("mitchell-show-primary-mobile");
        }
        if (
          htmlEl.classList.contains("mitchell-show-secondary-mobile") &&
          !targetEl.closest(".bd-sidebar-secondary, #pst-secondary-sidebar")
        ) {
          htmlEl.classList.remove("mitchell-show-secondary-mobile");
        }
      },
      true
    );

    document.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape") closeMobileDrawers();
    });
  }

  function initPredefinedOutputLock() {
    document.querySelectorAll("div.cell").forEach((cell) => {
      const outputDiv = cell.querySelector("div.cell_output");
      const hasRealContent =
        outputDiv &&
        (outputDiv.children.length > 0 || (outputDiv.textContent || "").trim().length > 0);
      if (hasRealContent) {
        cell.dataset.hasPredefinedOutput = "true";
      } else {
        cell.classList.add("mitchell-output-unlocked");
      }
    });
  }

  function stripOutputVeils() {
    document.querySelectorAll(".mitchell-output-veil").forEach((el) => el.remove());
  }

  function unlockCellOutput(cell) {
    if (!cell) return;
    cell.classList.add("mitchell-output-unlocked");
    cell.querySelectorAll(".mitchell-output-veil").forEach((el) => el.remove());
  }

  function unlockCellOutputById(cellId, cellObj) {
    let cell = null;
    if (cellObj && cellObj.area && cellObj.area.node) {
      cell = cellObj.area.node.closest("div.cell");
    }
    if (!cell && cellId) {
      const thebeEl = document.querySelector(`.thebe-cell[data-thebe-id="${cellId}"]`);
      if (thebeEl) {
        cell = thebeEl.closest("div.cell");
      }
    }
    if (cell) {
      unlockCellOutput(cell);
    }
  }

  function mountOutputVeils(onActivate) {
    document.querySelectorAll("div.cell").forEach((cell) => {
      if (
        cell.dataset.hasPredefinedOutput !== "true" ||
        cell.classList.contains("mitchell-output-unlocked")
      ) {
        return;
      }
      const outputDiv = cell.querySelector("div.cell_output");
      if (!outputDiv) return;

      outputDiv.querySelectorAll(".mitchell-output-veil").forEach((el) => el.remove());

      const veil = document.createElement("div");
      veil.className = "mitchell-output-veil";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mitchell-veil-btn";
      if (activated) {
        btn.innerHTML = `${ICONS.play}Run cell to reveal output`;
      } else if (activating) {
        btn.disabled = true;
        btn.innerHTML = `${ICONS.spinner}Connecting to Julia…`;
      } else {
        btn.innerHTML = `${ICONS.play}Activate Julia &amp; run to reveal output`;
      }

      btn.addEventListener("click", () => {
        if (activated) {
          const runBtn = cell.querySelector(".thebe-run-button, .thebelab-run-button");
          if (runBtn) {
            runBtn.click();
          }
        } else if (onActivate) {
          onActivate();
        }
      });

      const hint = document.createElement("span");
      hint.className = "mitchell-veil-hint";
      hint.textContent = activated
        ? "Click here or press Shift + Enter in the code cell above."
        : "Default output is hidden until you run this cell live.";

      veil.appendChild(btn);
      veil.appendChild(hint);
      outputDiv.appendChild(veil);
    });
  }

  /**
   * Prepare every notebook cell DOM node for Thebe, guaranteeing an exact 1-to-1
   * match between [data-executable] inputs and [data-output] containers even for
   * cells that have no pre-rendered outputs.
   */
  function prepareCellsForThebe() {
    // Remove any pre-activation helper pills & veils first so Thebe never captures them
    document.querySelectorAll(".mitchell-cell-activate-pill").forEach((el) => el.remove());
    stripOutputVeils();

    const cells = document.querySelectorAll("div.cell");
    cells.forEach((cell) => {
      const pre = cell.querySelector("div.cell_input pre") || cell.querySelector("pre");
      if (!pre) return;

      pre.setAttribute("data-executable", "true");
      // Thebe's bundled CodeMirror includes Python mode, which cleanly highlights
      // Julia # comments, single/triple-quoted strings, and numbers.
      pre.setAttribute("data-language", "python");
      pre.setAttribute("data-readonly", "false");

      let output = cell.querySelector("div.cell_output");
      if (!output) {
        output = document.createElement("div");
        output.className = "cell_output docutils container";
        cell.appendChild(output);
        cell.classList.add("mitchell-output-unlocked");
      }
      output.setAttribute("data-output", "true");

      // Remove sphinx-copybutton overlays so they don't clutter editable cells
      cell.querySelectorAll("button.copybtn").forEach((btn) => btn.remove());
    });
  }

  function createToolbar() {
    const bar = document.createElement("div");
    bar.id = "mitchell-live-toolbar";
    bar.className = "mitchell-live-toolbar";
    bar.innerHTML = `
      <div class="mitchell-live-left">
        <button id="mitchell-launch-btn" type="button" class="mitchell-btn mitchell-btn-primary">
          ${ICONS.play}Activate Live Editable Julia Cells
        </button>
        <span id="mitchell-status-pill" class="mitchell-status-pill mitchell-status-idle">
          Static preview
        </span>
        <span id="mitchell-status-msg" class="mitchell-status-msg">
          Default outputs are blurred — launch your private Julia kernel and run each cell to see your results.
        </span>
      </div>
      <div class="mitchell-live-right">
        <a id="mitchell-lab-link" class="mitchell-btn mitchell-btn-secondary" href="#" target="_blank" rel="noopener" style="display:none;">
          Open JupyterLab ↗
        </a>
        <button id="mitchell-reset-btn" type="button" class="mitchell-btn mitchell-btn-secondary" style="display:none;" title="Discard current container and start a fresh Julia workspace">
          ${ICONS.reset}Reset Session
        </button>
      </div>
    `;

    // Place sticky toolbar right at the top of the article so it stays visible while scrolling
    const article =
      document.querySelector("article.bd-article") ||
      document.querySelector("main#main-content") ||
      document.querySelector("main");
    if (article) {
      article.prepend(bar);
    }

    // Also add a quick-activate button in the top-right article header bar
    let headerBtn = null;
    const headerRight = document.querySelector(".article-header-buttons");
    if (headerRight) {
      headerBtn = document.createElement("button");
      headerBtn.type = "button";
      headerBtn.id = "mitchell-header-launch-btn";
      headerBtn.className = "btn btn-sm mitchell-header-live-btn";
      headerBtn.title = "Activate live editable Julia code cells";
      headerBtn.innerHTML = `${ICONS.play}Live Julia`;
      headerRight.prepend(headerBtn);
    }

    return {
      bar,
      launchBtn: bar.querySelector("#mitchell-launch-btn"),
      headerBtn,
      statusPill: bar.querySelector("#mitchell-status-pill"),
      statusMsg: bar.querySelector("#mitchell-status-msg"),
      labLink: bar.querySelector("#mitchell-lab-link"),
      resetBtn: bar.querySelector("#mitchell-reset-btn"),
    };
  }

  function addPreActivationCellPills(onActivate) {
    document.querySelectorAll("div.cell").forEach((cell) => {
      const inputDiv = cell.querySelector("div.cell_input");
      if (!inputDiv) return;
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "mitchell-cell-activate-pill";
      pill.innerHTML = `${ICONS.play}Click to edit &amp; run live in Julia`;
      pill.addEventListener("click", onActivate);
      inputDiv.appendChild(pill);
    });
  }

  function setStatus(ui, state, pillText, message) {
    ui.statusPill.className = `mitchell-status-pill mitchell-status-${state}`;
    ui.statusPill.textContent = pillText;
    ui.statusMsg.textContent = message;
  }

  async function activateThebe(ui) {
    if (activating || activated) return;
    const retryActivate = () => activateThebe(ui);
    activating = true;
    ui.launchBtn.disabled = true;
    ui.launchBtn.innerHTML = `${ICONS.spinner}Connecting to Julia…`;
    if (ui.headerBtn) {
      ui.headerBtn.disabled = true;
      ui.headerBtn.innerHTML = `${ICONS.spinner}Connecting…`;
    }
    mountOutputVeils(retryActivate);
    setStatus(
      ui,
      "loading",
      "Connecting…",
      "Loading interactive editor and connecting to kernels.mitchell.science…"
    );

    let lastServerError = "";
    try {
      loadStylesheet(THEBE_CSS_URL);
      await loadScript(THEBE_JS_URL);

      const serverImageId = await fetchServerImageId();
      if (serverImageId && hasSavedSession()) {
        let savedImageId = "";
        try {
          savedImageId = window.localStorage.getItem(IMAGE_ID_KEY) || "";
        } catch (_e) {
          savedImageId = "";
        }
        if (savedImageId && savedImageId !== serverImageId) {
          setStatus(
            ui,
            "loading",
            "Updating…",
            "A newer tutorial environment is available on the server — launching a fresh container…"
          );
          await stopSavedSessions();
          clearSavedSessions();
        }
      }

      prepareCellsForThebe();

      if (window.thebe && window.thebe.events) {
        window.thebe.events.on("status", (_evt, data) => {
          if (data && data.subject === "cell") {
            if (data.status === "executing" || data.status === "idle") {
              unlockCellOutputById(data.id, data.object);
            }
            return;
          }
          const msg = data && data.message ? data.message : "";
          const status = data && data.status ? data.status : "launching";
          if (status === "failed") {
            if (msg) lastServerError = msg;
            setStatus(ui, "error", "Connection Failed", msg || "Failed to launch Julia kernel.");
          } else if (status === "ready") {
            setStatus(
              ui,
              "ready",
              "Julia Ready",
              "Run each cell below (Shift + Enter or click Run) to reveal its live output."
            );
          } else {
            setStatus(ui, "loading", "Launching…", msg || `Status: ${status}`);
          }
        });

        window.thebe.events.on("error", (_evt, data) => {
          if (data && data.subject === "cell") {
            unlockCellOutputById(data.id, data.object);
            return;
          }
          const msg = (data && data.message) || lastServerError || "Failed to connect to Julia kernel server.";
          lastServerError = msg;
          setStatus(ui, "error", "Error", msg);
          ui.launchBtn.disabled = false;
          ui.launchBtn.innerHTML = `${ICONS.play}Retry Connection`;
          if (ui.headerBtn) {
            ui.headerBtn.disabled = false;
            ui.headerBtn.innerHTML = `${ICONS.play}Retry Julia`;
          }
          ui.resetBtn.style.display = "inline-flex";
          activating = false;
          mountOutputVeils(retryActivate);
        });
      }

      const result = await window.thebe.bootstrap({
        useBinder: true,
        requestKernel: true,
        predefinedOutput: true,
        mountStatusWidget: false,
        mountActivateWidget: false,
        mountRunButton: true,
        mountRunAllButton: true,
        mountRestartButton: true,
        mountRestartAllButton: true,
        selector: "[data-executable]",
        outputSelector: "[data-output]",
        binderOptions: BINDER_CONFIG,
        kernelOptions: {
          kernelName: "julia",
          path: "/",
        },
        savedSessionOptions: {
          enabled: true,
          maxAge: 7200,
          storagePrefix: STORAGE_PREFIX,
        },
        codeMirrorConfig: {
          theme: "default",
          mode: "python",
          readOnly: false,
          lineNumbers: true,
          autoRefresh: true,
          matchBrackets: true,
        },
      });

      if (serverImageId) {
        try {
          window.localStorage.setItem(IMAGE_ID_KEY, serverImageId);
        } catch (_e) {
          // Ignore storage restrictions
        }
      }

      activated = true;
      activating = false;
      ui.launchBtn.style.display = "none";
      if (ui.headerBtn) {
        ui.headerBtn.innerHTML = `${ICONS.check}Julia Live`;
        ui.headerBtn.classList.add("is-ready");
      }
      ui.resetBtn.style.display = "inline-flex";
      setStatus(
        ui,
        "ready",
        "Julia Ready",
        "Run each cell below (Shift + Enter or click Run) to reveal its live output."
      );
      mountOutputVeils(retryActivate);

      const creds = extractServerCredentials(result);
      if (creds) {
        activeSessionCreds = creds;
        let currentLabUrl = buildLabUrl(creds.baseUrl, creds.token, null);
        ui.labLink.href = currentLabUrl;
        ui.labLink.style.display = "inline-flex";

        // Pre-sync the current tutorial notebook into /home/jovyan/work in the background
        // so even middle-click / right-click opens JupyterLab directly on this task.
        syncCurrentNotebookToServer(creds).then((nbName) => {
          if (nbName) {
            currentLabUrl = buildLabUrl(creds.baseUrl, creds.token, nbName);
            ui.labLink.href = currentLabUrl;
          }
        });

        // On normal click, open a tab synchronously (avoids popup blockers), sync any
        // latest live edits from the CodeMirror cells, and navigate into JupyterLab.
        ui.labLink.addEventListener("click", async (evt) => {
          if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey || evt.button !== 0) {
            return;
          }
          evt.preventDefault();
          const labWin = window.open("about:blank", "_blank");
          if (labWin) {
            try {
              labWin.document.title = "Opening JupyterLab…";
              labWin.document.body.innerHTML =
                '<p style="font-family:system-ui,sans-serif;padding:2rem;color:#334155;">Syncing your current tutorial notebook and opening JupyterLab…</p>';
            } catch (_e) {
              // Ignore cross-origin/document errors
            }
          }
          const nbName = await syncCurrentNotebookToServer(creds);
          const targetUrl = buildLabUrl(creds.baseUrl, creds.token, nbName);
          currentLabUrl = targetUrl;
          ui.labLink.href = targetUrl;
          if (labWin) {
            labWin.opener = null;
            labWin.location.href = targetUrl;
          } else {
            window.open(targetUrl, "_blank", "noopener");
          }
        });
      }
    } catch (err) {
      console.error("[mitchell-thebe] Activation failed:", err);
      activating = false;
      ui.launchBtn.disabled = false;
      ui.launchBtn.innerHTML = `${ICONS.play}Retry Connection`;
      if (ui.headerBtn) {
        ui.headerBtn.disabled = false;
        ui.headerBtn.innerHTML = `${ICONS.play}Retry Julia`;
      }
      ui.resetBtn.style.display = "inline-flex";
      const detail =
        lastServerError ||
        (err && err.message) ||
        "Could not reach kernels.mitchell.science.";
      setStatus(ui, "error", "Connection Failed", detail);
      mountOutputVeils(retryActivate);
    }
  }

  /**
   * Extract normalized { baseUrl, token } for the active Jupyter Server session.
   */
  function extractServerCredentials(result) {
    const server = result && result.server ? result.server : null;
    if (!server) return null;

    const rawUrl =
      server.userServerUrl ||
      (server.settings && server.settings.baseUrl) ||
      (server.config && server.config.baseUrl) ||
      "";
    if (!rawUrl) return null;

    try {
      const parsed = new URL(rawUrl, window.location.href);
      const basePath = parsed.pathname.replace(/\/+$/, "") + "/";
      const baseUrl = `${parsed.origin}${basePath}`;
      let token =
        parsed.searchParams.get("token") ||
        (server.settings && server.settings.token) ||
        (server.config && server.config.token) ||
        "";

      if (!token) {
        // Fallback: check Thebe's saved session record in localStorage
        for (let i = 0; i < window.localStorage.length; i++) {
          const k = window.localStorage.key(i);
          if (k && k.startsWith(STORAGE_PREFIX)) {
            const saved = JSON.parse(window.localStorage.getItem(k) || "{}");
            if (saved && saved.token) {
              token = saved.token;
              break;
            }
          }
        }
      }

      return { baseUrl, token };
    } catch (_err) {
      return null;
    }
  }

  function buildLabUrl(baseUrl, token, notebookName) {
    const path = notebookName ? `lab/tree/${encodeURIComponent(notebookName)}` : "lab";
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${baseUrl}${path}${query}`;
  }

  /**
   * Locate the current page's source .ipynb URL (published by Jupyter Book under _sources/).
   */
  function findCurrentNotebookSource() {
    const dlLink = document.querySelector('a[href$=".ipynb"]');
    if (!dlLink) return null;
    try {
      const url = new URL(dlLink.getAttribute("href"), window.location.href);
      const filename = decodeURIComponent(url.pathname.split("/").pop() || "");
      if (!filename.endsWith(".ipynb")) return null;
      return { url: url.href, filename };
    } catch (_err) {
      return null;
    }
  }

  /**
   * Upload the current tutorial page's .ipynb (with any live CodeMirror edits merged in)
   * into the user's running JupyterLab workspace (/home/jovyan/work/<filename>).
   */
  async function syncCurrentNotebookToServer(creds) {
    const sourceInfo = findCurrentNotebookSource();
    if (!sourceInfo || !creds || !creds.baseUrl) return null;

    try {
      const resp = await fetch(sourceInfo.url);
      if (!resp.ok) return null;
      const nb = await resp.json();

      // Merge any live edits the student has already made in the in-page CodeMirror cells
      if (Array.isArray(nb.cells)) {
        const liveEditors = Array.from(document.querySelectorAll(".thebelab-cell .CodeMirror"))
          .map((el) => (el.CodeMirror ? el.CodeMirror.getValue() : null))
          .filter((val) => val !== null);
        const codeCells = nb.cells.filter((c) => c && c.cell_type === "code");
        if (liveEditors.length > 0 && liveEditors.length === codeCells.length) {
          codeCells.forEach((cell, idx) => {
            cell.source = liveEditors[idx];
          });
        }
      }

      // Ensure JupyterLab opens the notebook directly on our precompiled Julia kernel
      nb.metadata = nb.metadata || {};
      nb.metadata.kernelspec = {
        display_name: "Julia",
        language: "julia",
        name: "julia",
      };

      const putUrl = `${creds.baseUrl}api/contents/${encodeURIComponent(sourceInfo.filename)}${
        creds.token ? `?token=${encodeURIComponent(creds.token)}` : ""
      }`;
      const putResp = await fetch(putUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "notebook",
          format: "json",
          content: nb,
        }),
      });
      return putResp.ok ? sourceInfo.filename : null;
    } catch (err) {
      console.warn("[mitchell-thebe] Could not sync notebook to JupyterLab:", err);
      return null;
    }
  }

  runWhenReady(() => {
    wireSidebarToggles();

    const cells = document.querySelectorAll("div.cell");
    if (cells.length === 0) return;

    initPredefinedOutputLock();

    const ui = createToolbar();
    const triggerActivate = () => activateThebe(ui);

    ui.launchBtn.addEventListener("click", triggerActivate);
    if (ui.headerBtn) {
      ui.headerBtn.addEventListener("click", triggerActivate);
    }
    ui.resetBtn.addEventListener("click", async () => {
      ui.resetBtn.disabled = true;
      ui.resetBtn.innerHTML = `${ICONS.spinner}Resetting…`;
      await stopSavedSessions(activeSessionCreds);
      clearSavedSessions();
      window.location.reload();
    });

    addPreActivationCellPills(triggerActivate);
    mountOutputVeils(triggerActivate);

    // If the student already launched a Julia session on another chapter,
    // seamlessly reconnect on this page so cells are editable immediately.
    if (hasSavedSession()) {
      activateThebe(ui);
    }
  });
})();
