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
   * sidebars across all viewport widths (desktop collapse + narrow drawer).
   * Uses querySelectorAll because sphinx-book-theme renders duplicate toggle
   * buttons in .bd-header and .bd-header-article.
   */
  function wireSidebarToggles() {
    const htmlEl = document.documentElement;

    function closeMobileDrawers() {
      htmlEl.classList.remove("mitchell-show-primary-mobile", "mitchell-show-secondary-mobile");
    }

    const primaryToggles = document.querySelectorAll(
      ".primary-toggle, button[title='Toggle primary sidebar'], label[for='__primary']"
    );
    primaryToggles.forEach((btn) => {
      btn.addEventListener(
        "click",
        (evt) => {
          evt.preventDefault();
          evt.stopImmediatePropagation();
          if (window.matchMedia("(min-width: 992px)").matches) {
            htmlEl.classList.toggle("mitchell-hide-primary-sidebar");
          } else {
            htmlEl.classList.remove("mitchell-show-secondary-mobile");
            htmlEl.classList.toggle("mitchell-show-primary-mobile");
          }
        },
        true
      );
    });

    const secondaryToggles = document.querySelectorAll(
      ".secondary-toggle, button[title='Toggle secondary sidebar'], label[for='__secondary']"
    );
    secondaryToggles.forEach((btn) => {
      btn.addEventListener(
        "click",
        (evt) => {
          evt.preventDefault();
          evt.stopImmediatePropagation();
          if (window.matchMedia("(min-width: 1200px)").matches) {
            htmlEl.classList.toggle("mitchell-hide-secondary-sidebar");
          } else {
            htmlEl.classList.remove("mitchell-show-primary-mobile");
            htmlEl.classList.toggle("mitchell-show-secondary-mobile");
          }
        },
        true
      );
    });

    document.addEventListener("keydown", (evt) => {
      if (evt.key === "Escape") closeMobileDrawers();
    });

    document.addEventListener("click", (evt) => {
      if (
        htmlEl.classList.contains("mitchell-show-primary-mobile") &&
        !evt.target.closest(".bd-sidebar-primary, #pst-primary-sidebar, .primary-toggle")
      ) {
        htmlEl.classList.remove("mitchell-show-primary-mobile");
      }
      if (
        htmlEl.classList.contains("mitchell-show-secondary-mobile") &&
        !evt.target.closest(".bd-sidebar-secondary, #pst-secondary-sidebar, .secondary-toggle")
      ) {
        htmlEl.classList.remove("mitchell-show-secondary-mobile");
      }
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

      if (result && result.server && result.server.userServerUrl) {
        ui.labLink.href = result.server.userServerUrl;
        ui.labLink.style.display = "inline-flex";
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
