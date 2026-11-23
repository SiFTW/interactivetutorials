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
   * Prepare every notebook cell DOM node for Thebe, guaranteeing an exact 1-to-1
   * match between [data-executable] inputs and [data-output] containers even for
   * cells that have no pre-rendered outputs.
   */
  function prepareCellsForThebe() {
    const cells = document.querySelectorAll("div.cell");
    cells.forEach((cell) => {
      const pre = cell.querySelector("div.cell_input pre");
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

    const h1 = document.querySelector("article.bd-article h1, main h1");
    if (h1 && h1.parentNode) {
      h1.insertAdjacentElement("afterend", bar);
    } else {
      const article = document.querySelector("article.bd-article, main");
      if (article) article.prepend(bar);
    }

    return {
      bar,
      launchBtn: bar.querySelector("#mitchell-launch-btn"),
      statusPill: bar.querySelector("#mitchell-status-pill"),
      statusMsg: bar.querySelector("#mitchell-status-msg"),
      labLink: bar.querySelector("#mitchell-lab-link"),
      resetBtn: bar.querySelector("#mitchell-reset-btn"),
    };
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
    setStatus(ui, "loading", "Connecting…", "Loading interactive editor and connecting to kernels.mitchell.science…");

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
      ui.resetBtn.style.display = "inline-flex";
      setStatus(
        ui,
        "error",
        "Connection Failed",
        err && err.message ? err.message : "Could not reach kernels.mitchell.science."
      );
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const cells = document.querySelectorAll("div.cell");
    if (cells.length === 0) return;

    const ui = createToolbar();
    ui.launchBtn.addEventListener("click", () => activateThebe(ui));
    ui.resetBtn.addEventListener("click", () => {
      clearSavedSessions();
      window.location.reload();
    });

    // If the student already launched a Julia session on another chapter,
    // seamlessly reconnect on this page so cells are editable immediately.
    if (hasSavedSession()) {
      activateThebe(ui);
    }
  });
})();
