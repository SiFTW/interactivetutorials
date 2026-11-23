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

  let activating = false;
  let activated = false;

  function runWhenReady(cb) {
    if (document.readyState !== "loading") {
      cb();
    } else {
      document.addEventListener("DOMContentLoaded", cb);
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
        if (key && (key.startsWith(STORAGE_PREFIX) || key.startsWith("thebe-binder"))) {
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

  /**
   * Prepare every notebook cell DOM node for Thebe, guaranteeing an exact 1-to-1
   * match between [data-executable] inputs and [data-output] containers even for
   * cells that have no pre-rendered outputs.
   */
  function prepareCellsForThebe() {
    // Remove any pre-activation helper pills first
    document.querySelectorAll(".mitchell-cell-activate-pill").forEach((el) => el.remove());

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
          ⚡ Activate Live Editable Julia Cells
        </button>
        <span id="mitchell-status-pill" class="mitchell-status-pill mitchell-status-idle">
          Static preview
        </span>
        <span id="mitchell-status-msg" class="mitchell-status-msg">
          Click to launch your private Julia kernel and edit any code cell below.
        </span>
      </div>
      <div class="mitchell-live-right">
        <a id="mitchell-lab-link" class="mitchell-btn mitchell-btn-secondary" href="#" target="_blank" rel="noopener" style="display:none;">
          Open JupyterLab ↗
        </a>
        <button id="mitchell-reset-btn" type="button" class="mitchell-btn mitchell-btn-secondary" style="display:none;" title="Discard current container and start a fresh Julia workspace">
          🔄 Reset Session
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
      headerBtn.textContent = "⚡ Live Julia";
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
      pill.textContent = "⚡ Click to edit & run live in Julia";
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
    activating = true;
    ui.launchBtn.disabled = true;
    ui.launchBtn.textContent = "⏳ Connecting to Julia…";
    if (ui.headerBtn) {
      ui.headerBtn.disabled = true;
      ui.headerBtn.textContent = "⏳ Connecting…";
    }
    setStatus(
      ui,
      "loading",
      "Connecting…",
      "Loading interactive editor and connecting to kernels.mitchell.science…"
    );

    try {
      loadStylesheet(THEBE_CSS_URL);
      await loadScript(THEBE_JS_URL);

      prepareCellsForThebe();

      if (window.thebe && window.thebe.events) {
        window.thebe.events.on("status", (_evt, data) => {
          const msg = data && data.message ? data.message : "";
          const status = data && data.status ? data.status : "launching";
          if (status === "ready") {
            setStatus(
              ui,
              "ready",
              "Julia Ready",
              "Click inside any code cell to edit, then press Shift + Enter (or click Run)."
            );
          } else {
            setStatus(ui, "loading", "Launching…", msg || `Status: ${status}`);
          }
        });

        window.thebe.events.on("error", (_evt, data) => {
          const msg = (data && data.message) || "Failed to connect to Julia kernel server.";
          setStatus(ui, "error", "Error", msg);
          ui.launchBtn.disabled = false;
          ui.launchBtn.textContent = "⚡ Retry Connection";
          if (ui.headerBtn) {
            ui.headerBtn.disabled = false;
            ui.headerBtn.textContent = "⚡ Retry Julia";
          }
          ui.resetBtn.style.display = "inline-flex";
          activating = false;
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

      activated = true;
      activating = false;
      ui.launchBtn.style.display = "none";
      if (ui.headerBtn) {
        ui.headerBtn.textContent = "✅ Julia Live";
        ui.headerBtn.classList.add("is-ready");
      }
      ui.resetBtn.style.display = "inline-flex";
      setStatus(
        ui,
        "ready",
        "Julia Ready",
        "Click inside any code cell to edit, then press Shift + Enter (or click Run)."
      );

      const creds = extractServerCredentials(result);
      if (creds) {
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
      ui.launchBtn.textContent = "⚡ Retry Connection";
      if (ui.headerBtn) {
        ui.headerBtn.disabled = false;
        ui.headerBtn.textContent = "⚡ Retry Julia";
      }
      ui.resetBtn.style.display = "inline-flex";
      setStatus(
        ui,
        "error",
        "Connection Failed",
        err && err.message ? err.message : "Could not reach kernels.mitchell.science."
      );
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

    const ui = createToolbar();
    const triggerActivate = () => activateThebe(ui);

    ui.launchBtn.addEventListener("click", triggerActivate);
    if (ui.headerBtn) {
      ui.headerBtn.addEventListener("click", triggerActivate);
    }
    ui.resetBtn.addEventListener("click", () => {
      clearSavedSessions();
      window.location.reload();
    });

    addPreActivationCellPills(triggerActivate);

    // If the student already launched a Julia session on another chapter,
    // seamlessly reconnect on this page so cells are editable immediately.
    if (hasSavedSession()) {
      activateThebe(ui);
    }
  });
})();
