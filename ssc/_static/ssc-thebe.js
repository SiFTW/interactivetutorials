/**
 * Mitchell Lab BSMS SSC Interactive Book Controller
 *
 * Provides:
 *  1. Reliable primary & secondary sidebar toggles across all viewport widths.
 *  2. Classroom Presentation Mode ("📽️ Present") that steps section-by-section
 *     as full-bleed slides while keeping live Julia CodeMirror cells interactive,
 *     with seamless return to continuous Reading Mode for students.
 *  3. Live editable Julia code cells via Thebe 0.9 + https://kernels.mitchell.science.
 *  4. "Open JupyterLab ↗" button that syncs the current SSC notebook (including
 *     live edits) into /home/jovyan/work/ and opens full JupyterLab.
 */
(function () {
  "use strict";

  const THEBE_JS_URL = "https://unpkg.com/thebe@0.9.2/lib/index.js";
  const THEBE_CSS_URL = "https://unpkg.com/thebe@0.9.2/lib/thebe.css";
  const BINDER_CONFIG = {
    repo: "SiFTW/interactivetutorials",
    ref: "main",
    binderUrl: "https://kernels.mitchell.science",
    repoProvider: "github",
  };
  const STORAGE_PREFIX = "mitchell-thebe-session-";
  const IMAGE_ID_KEY = "mitchell-thebe-kernel-image-id";

  let activating = false;
  let activated = false;
  let activeSessionCreds = null;

  function runWhenReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
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
      // Ignore storage access errors
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
          const raw = window.localStorage.getItem(key);
          if (!raw) continue;
          const data = JSON.parse(raw);
          if (data && data.lastUsed) {
            const ageSec = (Date.now() - new Date(data.lastUsed).getTime()) / 1000;
            if (ageSec < 7200) return true;
          }
        }
      }
    } catch (_err) {
      // Ignore storage access errors
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
            key.startsWith("thebe-binder-") ||
            key === IMAGE_ID_KEY)
        ) {
          toRemove.push(key);
        }
      }
      toRemove.forEach((k) => window.localStorage.removeItem(k));
    } catch (_err) {
      // Ignore storage access errors
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

  /* =========================================================================
     1. Reliable Sidebar Toggles (Desktop collapse + Narrow slide-over drawer)
     ========================================================================= */
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

        if (
          htmlEl.classList.contains("mitchell-show-secondary-mobile") &&
          targetEl.closest(".bd-sidebar-secondary a[href^='#'], #pst-secondary-sidebar a[href^='#']")
        ) {
          htmlEl.classList.remove("mitchell-show-secondary-mobile");
          return;
        }

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

  /* =========================================================================
     2. Classroom Presentation Mode (Slides <-> Reading Mode)
     ========================================================================= */
  function wirePresentMode() {
    const article =
      document.querySelector("article.bd-article") ||
      document.querySelector("main#main-content") ||
      document.querySelector("main");
    if (!article) return null;

    // Collect slide groups from the real DOM without cloning (preserves live Thebe cells!)
    function buildSlideGroups() {
      const rootSection = article.querySelector(":scope > section") || article;
      const directChildren = Array.from(rootSection.children);
      const slides = [];

      // Slide 0: Title (<h1>) + intro elements before the first nested <section>
      const introNodes = [];
      const childSections = [];
      for (const el of directChildren) {
        if (el.id === "mitchell-live-toolbar") continue;
        if (el.tagName === "SECTION") {
          childSections.push(el);
        } else {
          introNodes.push(el);
        }
      }

      if (introNodes.length > 0) {
        const h1 = rootSection.querySelector(":scope > h1");
        const title = h1 ? h1.textContent.replace(/#$/, "").trim() : document.title;
        slides.push({ title, nodes: introNodes });
      }

      for (const sec of childSections) {
        const h = sec.querySelector(":scope > h2, :scope > h3, :scope > h1");
        const title = h ? h.textContent.replace(/#$/, "").trim() : "Section";
        slides.push({ title, nodes: [sec] });
      }

      if (slides.length === 0) {
        slides.push({ title: document.title, nodes: [rootSection] });
      }
      return slides;
    }

    function getAdjacentChapterUrl(selector) {
      const link = document.querySelector(selector);
      if (!link || !link.getAttribute("href")) return null;
      try {
        const url = new URL(link.getAttribute("href"), window.location.href);
        url.searchParams.set("present", "1");
        return url.href;
      } catch (_err) {
        return null;
      }
    }

    // Create floating bottom Presenter Bar
    const presentBar = document.createElement("div");
    presentBar.id = "mitchell-present-bar";
    presentBar.innerHTML = `
      <button type="button" id="mitchell-present-prev">← Prev</button>
      <select id="mitchell-present-select" aria-label="Jump to slide"></select>
      <button type="button" id="mitchell-present-next">Next →</button>
      <button type="button" id="mitchell-present-fs" title="Toggle browser fullscreen">⛶ Fullscreen</button>
      <button type="button" id="mitchell-present-exit" class="mitchell-present-exit" title="Return to continuous student reading mode (Esc)">📖 Reading Mode</button>
    `;
    document.body.appendChild(presentBar);

    const prevBtn = presentBar.querySelector("#mitchell-present-prev");
    const nextBtn = presentBar.querySelector("#mitchell-present-next");
    const selectEl = presentBar.querySelector("#mitchell-present-select");
    const fsBtn = presentBar.querySelector("#mitchell-present-fs");
    const exitBtn = presentBar.querySelector("#mitchell-present-exit");

    let slides = [];
    let currentIdx = 0;
    let isPresenting = false;

    function refreshCodeMirrorsIn(nodes) {
      window.requestAnimationFrame(() => {
        nodes.forEach((node) => {
          node.querySelectorAll(".CodeMirror").forEach((cmEl) => {
            if (cmEl.CodeMirror && typeof cmEl.CodeMirror.refresh === "function") {
              cmEl.CodeMirror.refresh();
            }
          });
        });
      });
    }

    function showSlide(index) {
      if (!slides.length) return;
      currentIdx = Math.max(0, Math.min(index, slides.length - 1));

      slides.forEach((slide, i) => {
        const active = i === currentIdx;
        slide.nodes.forEach((node) => {
          node.classList.toggle("mitchell-slide-hidden", !active);
        });
      });

      selectEl.value = String(currentIdx);

      const prevChapter = getAdjacentChapterUrl("a.left-prev");
      const nextChapter = getAdjacentChapterUrl("a.right-next");

      if (currentIdx === 0) {
        prevBtn.disabled = !prevChapter;
        prevBtn.textContent = prevChapter ? "← Prev Chapter" : "← Prev";
      } else {
        prevBtn.disabled = false;
        prevBtn.textContent = "← Prev";
      }

      if (currentIdx === slides.length - 1) {
        nextBtn.disabled = !nextChapter;
        nextBtn.textContent = nextChapter ? "Next Chapter →" : "End";
      } else {
        nextBtn.disabled = false;
        nextBtn.textContent = "Next →";
      }

      window.scrollTo({ top: 0, behavior: "instant" });
      refreshCodeMirrorsIn(slides[currentIdx].nodes);
    }

    function enterPresentMode(startIdx = 0) {
      slides = buildSlideGroups();
      selectEl.innerHTML = "";
      slides.forEach((slide, i) => {
        const opt = document.createElement("option");
        opt.value = String(i);
        opt.textContent = `${i + 1} / ${slides.length} · ${slide.title}`;
        selectEl.appendChild(opt);
      });

      isPresenting = true;
      document.documentElement.classList.add("mitchell-present-mode");

      try {
        const url = new URL(window.location.href);
        url.searchParams.set("present", "1");
        window.history.replaceState({}, "", url.toString());
      } catch (_err) {
        // Ignore history errors
      }

      showSlide(startIdx);
    }

    function exitPresentMode() {
      if (!isPresenting) return;
      isPresenting = false;
      document.documentElement.classList.remove("mitchell-present-mode");
      slides.forEach((slide) => {
        slide.nodes.forEach((node) => node.classList.remove("mitchell-slide-hidden"));
      });

      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }

      try {
        const url = new URL(window.location.href);
        url.searchParams.delete("present");
        window.history.replaceState({}, "", url.toString());
      } catch (_err) {
        // Ignore history errors
      }

      // Refresh any CodeMirror cells after returning to full page view
      window.requestAnimationFrame(() => {
        document.querySelectorAll(".CodeMirror").forEach((cmEl) => {
          if (cmEl.CodeMirror && typeof cmEl.CodeMirror.refresh === "function") {
            cmEl.CodeMirror.refresh();
          }
        });
      });
    }

    prevBtn.addEventListener("click", () => {
      if (currentIdx > 0) {
        showSlide(currentIdx - 1);
      } else {
        const prevChapter = getAdjacentChapterUrl("a.left-prev");
        if (prevChapter) window.location.href = prevChapter;
      }
    });

    nextBtn.addEventListener("click", () => {
      if (currentIdx < slides.length - 1) {
        showSlide(currentIdx + 1);
      } else {
        const nextChapter = getAdjacentChapterUrl("a.right-next");
        if (nextChapter) window.location.href = nextChapter;
      }
    });

    selectEl.addEventListener("change", () => {
      showSlide(parseInt(selectEl.value, 10) || 0);
    });

    fsBtn.addEventListener("click", () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen?.().catch(() => {});
      } else {
        document.exitFullscreen?.().catch(() => {});
      }
    });

    exitBtn.addEventListener("click", exitPresentMode);

    document.addEventListener("keydown", (evt) => {
      if (!isPresenting) return;
      const active = document.activeElement;
      const isEditing =
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          active.tagName === "SELECT" ||
          active.isContentEditable ||
          (active.closest && active.closest(".CodeMirror")));

      if (evt.key === "Escape" && !isEditing) {
        evt.preventDefault();
        exitPresentMode();
        return;
      }
      if (isEditing) return;

      if (evt.key === "ArrowRight" || evt.key === "PageDown") {
        evt.preventDefault();
        nextBtn.click();
      } else if (evt.key === "ArrowLeft" || evt.key === "PageUp") {
        evt.preventDefault();
        prevBtn.click();
      }
    });

    // Add a quick "📽️ Present" button in the top-right article header bar on EVERY page
    const headerRight = document.querySelector(".article-header-buttons");
    if (headerRight) {
      const headerPresentBtn = document.createElement("button");
      headerPresentBtn.type = "button";
      headerPresentBtn.id = "mitchell-header-present-btn";
      headerPresentBtn.className = "btn btn-sm mitchell-header-present-btn";
      headerPresentBtn.title = "Switch to full-screen slide Presentation Mode for class";
      headerPresentBtn.textContent = "📽️ Present";
      headerPresentBtn.addEventListener("click", () => enterPresentMode(0));
      headerRight.prepend(headerPresentBtn);
    }

    // Auto-enter Present Mode if navigated with ?present=1
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get("present") === "1") {
        enterPresentMode(0);
      }
    } catch (_err) {
      // Ignore URL parse errors
    }

    return { enterPresentMode, exitPresentMode };
  }

  /* =========================================================================
     3. Live Editable Cells (Julia & Python via Thebe 0.9) & JupyterLab Sync
     ========================================================================= */
  function detectPageKernel() {
    const pyEl = document.querySelector(
      "div.cell div.cell_input .highlight-ipython3, div.cell div.cell_input .highlight-python, div.cell div.cell_input .highlight-python3"
    );
    const jlEl = document.querySelector("div.cell div.cell_input .highlight-julia");
    if (pyEl && !jlEl) {
      return {
        kernelName: "python3",
        language: "python",
        displayName: "Python 3",
        shortLabel: "Python",
        codeMirrorMode: "python",
      };
    }
    return {
      kernelName: "julia",
      language: "julia",
      displayName: "Julia",
      shortLabel: "Julia",
      codeMirrorMode: "python",
    };
  }

  function prepareCellsForThebe(kernel) {
    document.querySelectorAll(".mitchell-cell-activate-pill").forEach((el) => el.remove());

    document.querySelectorAll("div.cell").forEach((cell) => {
      const inputDiv = cell.querySelector("div.cell_input");
      const pre = inputDiv ? inputDiv.querySelector("pre") : null;
      if (!pre) return;

      const rawCode = pre.textContent || "";
      pre.setAttribute("data-executable", "true");
      pre.setAttribute("data-language", kernel.language);
      pre.textContent = rawCode;

      let outputDiv = cell.querySelector("div.cell_output");
      if (!outputDiv) {
        outputDiv = document.createElement("div");
        outputDiv.className = "cell_output docutils container";
        cell.appendChild(outputDiv);
      }
      outputDiv.setAttribute("data-output", "true");

      cell.querySelectorAll("button.copybtn").forEach((btn) => btn.remove());
    });
  }

  function createToolbar(hasCodeCells, presentApi, kernel) {
    const bar = document.createElement("div");
    bar.id = "mitchell-live-toolbar";
    bar.className = "mitchell-live-toolbar";
    const lang = kernel.shortLabel;

    if (hasCodeCells) {
      bar.innerHTML = `
        <div class="mitchell-live-left">
          <button id="mitchell-launch-btn" type="button" class="mitchell-btn mitchell-btn-primary">
            ⚡ Activate Live Editable ${lang} Cells
          </button>
          <span id="mitchell-status-pill" class="mitchell-status-pill mitchell-status-idle">
            Reading mode
          </span>
          <span id="mitchell-status-msg" class="mitchell-status-msg">
            Read at your own pace, or click to run &amp; edit live ${lang} simulations.
          </span>
        </div>
        <div class="mitchell-live-right">
          <button id="mitchell-present-btn" type="button" class="mitchell-btn mitchell-btn-present" title="Present this chapter as interactive slides in class">
            📽️ Present Slides
          </button>
          <a id="mitchell-lab-link" class="mitchell-btn mitchell-btn-secondary" href="#" target="_blank" rel="noopener" style="display:none;">
            Open JupyterLab ↗
          </a>
          <button id="mitchell-reset-btn" type="button" class="mitchell-btn mitchell-btn-secondary" style="display:none;" title="Discard current container and start a fresh workspace">
            🔄 Reset Session
          </button>
        </div>
      `;
    } else {
      bar.classList.add("mitchell-toolbar-nocode");
      bar.innerHTML = `
        <div class="mitchell-live-left">
          <span class="mitchell-status-pill mitchell-status-idle">Reading mode</span>
          <span class="mitchell-status-msg">
            Scroll to read at your own pace, or switch to full-screen Slide Mode for class.
          </span>
        </div>
        <div class="mitchell-live-right">
          <button id="mitchell-present-btn" type="button" class="mitchell-btn mitchell-btn-present" title="Present this page as full-screen slides">
            📽️ Present Slides
          </button>
        </div>
      `;
    }

    const article =
      document.querySelector("article.bd-article") ||
      document.querySelector("main#main-content") ||
      document.querySelector("main");
    if (article) {
      article.prepend(bar);
    }

    const presentBtn = bar.querySelector("#mitchell-present-btn");
    if (presentBtn && presentApi) {
      presentBtn.addEventListener("click", () => presentApi.enterPresentMode(0));
    }

    let headerBtn = null;
    if (hasCodeCells) {
      const headerRight = document.querySelector(".article-header-buttons");
      if (headerRight) {
        headerBtn = document.createElement("button");
        headerBtn.type = "button";
        headerBtn.id = "mitchell-header-launch-btn";
        headerBtn.className = "btn btn-sm mitchell-header-live-btn";
        headerBtn.title = `Activate live editable ${lang} code cells`;
        headerBtn.textContent = `⚡ Live ${lang}`;
        headerRight.prepend(headerBtn);
      }
    }

    return {
      bar,
      kernel,
      launchBtn: bar.querySelector("#mitchell-launch-btn"),
      headerBtn,
      statusPill: bar.querySelector("#mitchell-status-pill"),
      statusMsg: bar.querySelector("#mitchell-status-msg"),
      labLink: bar.querySelector("#mitchell-lab-link"),
      resetBtn: bar.querySelector("#mitchell-reset-btn"),
    };
  }

  function addPreActivationCellPills(onActivate, kernel) {
    document.querySelectorAll("div.cell").forEach((cell) => {
      const inputDiv = cell.querySelector("div.cell_input");
      if (!inputDiv) return;
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "mitchell-cell-activate-pill";
      pill.textContent = `⚡ Click to edit & run live in ${kernel.shortLabel}`;
      pill.addEventListener("click", onActivate);
      inputDiv.appendChild(pill);
    });
  }

  function setStatus(ui, state, pillText, message) {
    if (!ui.statusPill || !ui.statusMsg) return;
    ui.statusPill.className = `mitchell-status-pill mitchell-status-${state}`;
    ui.statusPill.textContent = pillText;
    ui.statusMsg.textContent = message;
  }

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

  async function syncCurrentNotebookToServer(creds, kernel) {
    const sourceInfo = findCurrentNotebookSource();
    if (!sourceInfo || !creds || !creds.baseUrl) return null;

    try {
      const resp = await fetch(sourceInfo.url);
      if (!resp.ok) return null;
      const nb = await resp.json();

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

      nb.metadata = nb.metadata || {};
      nb.metadata.kernelspec = {
        display_name: kernel.displayName,
        language: kernel.language,
        name: kernel.kernelName,
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
      console.warn("[ssc-thebe] Could not sync notebook to JupyterLab:", err);
      return null;
    }
  }

  async function activateThebe(ui) {
    if (activating || activated) return;
    const kernel = ui.kernel;
    const lang = kernel.shortLabel;
    activating = true;
    ui.launchBtn.disabled = true;
    ui.launchBtn.textContent = `⏳ Connecting to ${lang}…`;
    if (ui.headerBtn) {
      ui.headerBtn.disabled = true;
      ui.headerBtn.textContent = "⏳ Connecting…";
    }
    setStatus(
      ui,
      "loading",
      "Connecting…",
      `Loading interactive editor and connecting to ${lang} kernel on kernels.mitchell.science…`
    );

    let lastServerError = "";
    try {
      loadStylesheet(THEBE_CSS_URL);
      await loadScript(THEBE_JS_URL);

      // If the server deployed a newer kernel image since this browser cached a session,
      // automatically retire the old container so students get the latest teaching files.
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

      prepareCellsForThebe(kernel);

      if (window.thebe && window.thebe.events) {
        window.thebe.events.on("status", (_evt, data) => {
          const msg = data && data.message ? data.message : "";
          const status = data && data.status ? data.status : "launching";
          if (status === "failed") {
            if (msg) lastServerError = msg;
            setStatus(ui, "error", "Connection Failed", msg || `Failed to launch ${lang} kernel.`);
          } else if (status === "ready") {
            setStatus(
              ui,
              "ready",
              `${lang} Ready`,
              "Edit any parameter or code below, then press Shift + Enter (or click Run)."
            );
          } else {
            setStatus(ui, "loading", "Launching…", msg || `Status: ${status}`);
          }
        });

        window.thebe.events.on("error", (_evt, data) => {
          const msg = (data && data.message) || lastServerError || `Failed to connect to ${lang} kernel server.`;
          lastServerError = msg;
          setStatus(ui, "error", "Error", msg);
          ui.launchBtn.disabled = false;
          ui.launchBtn.textContent = "⚡ Retry Connection";
          if (ui.headerBtn) {
            ui.headerBtn.disabled = false;
            ui.headerBtn.textContent = `⚡ Retry ${lang}`;
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
          kernelName: kernel.kernelName,
          path: `/${kernel.kernelName}.ipynb`,
        },
        savedSessionOptions: {
          enabled: true,
          maxAge: 7200,
          storagePrefix: STORAGE_PREFIX,
        },
        codeMirrorConfig: {
          theme: "default",
          mode: kernel.codeMirrorMode,
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
          // Ignore storage access errors
        }
      }

      activated = true;
      activating = false;
      ui.launchBtn.style.display = "none";
      if (ui.headerBtn) {
        ui.headerBtn.textContent = `✅ ${lang} Live`;
        ui.headerBtn.classList.add("is-ready");
      }
      ui.resetBtn.style.display = "inline-flex";
      setStatus(
        ui,
        "ready",
        `${lang} Ready`,
        "Edit any parameter or code below, then press Shift + Enter (or click Run)."
      );

      const creds = extractServerCredentials(result);
      if (creds) {
        activeSessionCreds = creds;
        // Verify the connected container actually provides the requested kernel & MD workspace
        const tokenQs = creds.token ? `?token=${encodeURIComponent(creds.token)}` : "";
        const ksUrl = `${creds.baseUrl}api/kernelspecs${tokenQs}`;
        fetch(ksUrl)
          .then((r) => (r.ok ? r.json() : null))
          .then(async (data) => {
            const specs = data && data.kernelspecs ? data.kernelspecs : null;
            if (specs && !Object.prototype.hasOwnProperty.call(specs, kernel.kernelName)) {
              const avail = Object.keys(specs).join(", ") || "none";
              if (ui.headerBtn) {
                ui.headerBtn.textContent = "⚠️ Reset Needed";
                ui.headerBtn.classList.remove("is-ready");
              }
              setStatus(
                ui,
                "error",
                "Kernel Mismatch",
                `Connected container only has [${avail}] (missing '${kernel.kernelName}'). Click 🔄 Reset Session to launch a fresh ${lang} container.`
              );
              return;
            }
            if (kernel.kernelName === "python3") {
              const mdUrl = `${creds.baseUrl}api/contents/MD?content=0${
                creds.token ? `&token=${encodeURIComponent(creds.token)}` : ""
              }`;
              const mdResp = await fetch(mdUrl);
              if (!mdResp.ok) {
                if (ui.headerBtn) {
                  ui.headerBtn.textContent = "⚠️ Reset Needed";
                  ui.headerBtn.classList.remove("is-ready");
                }
                setStatus(
                  ui,
                  "error",
                  "Update Pending",
                  "This container was built before the Python MD stack (OpenMM / MDAnalysis) was installed. Click 🔄 Reset Session once the server update completes."
                );
              }
            }
          })
          .catch(() => {});

        let currentLabUrl = buildLabUrl(creds.baseUrl, creds.token, null);
        ui.labLink.href = currentLabUrl;
        ui.labLink.style.display = "inline-flex";

        syncCurrentNotebookToServer(creds, kernel).then((nbName) => {
          if (nbName) {
            currentLabUrl = buildLabUrl(creds.baseUrl, creds.token, nbName);
            ui.labLink.href = currentLabUrl;
          }
        });

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
                '<p style="font-family:system-ui,sans-serif;padding:2rem;color:#334155;">Syncing your current SSC notebook and opening JupyterLab…</p>';
            } catch (_e) {
              // Ignore document write errors
            }
          }
          const nbName = await syncCurrentNotebookToServer(creds, kernel);
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
      console.error("[ssc-thebe] Activation failed:", err);
      activating = false;
      ui.launchBtn.disabled = false;
      ui.launchBtn.textContent = "⚡ Retry Connection";
      if (ui.headerBtn) {
        ui.headerBtn.disabled = false;
        ui.headerBtn.textContent = `⚡ Retry ${lang}`;
      }
      ui.resetBtn.style.display = "inline-flex";
      const detail =
        lastServerError ||
        (err && err.message) ||
        "Could not reach kernels.mitchell.science.";
      setStatus(ui, "error", "Connection Failed", detail);
    }
  }

  runWhenReady(() => {
    wireSidebarToggles();
    const presentApi = wirePresentMode();

    const cells = document.querySelectorAll("div.cell");
    const hasCodeCells = cells.length > 0;
    const kernel = detectPageKernel();
    const ui = createToolbar(hasCodeCells, presentApi, kernel);

    if (!hasCodeCells) return;

    const triggerActivate = () => activateThebe(ui);
    ui.launchBtn.addEventListener("click", triggerActivate);
    if (ui.headerBtn) {
      ui.headerBtn.addEventListener("click", triggerActivate);
    }
    ui.resetBtn.addEventListener("click", async () => {
      ui.resetBtn.disabled = true;
      ui.resetBtn.textContent = "⏳ Resetting…";
      await stopSavedSessions(activeSessionCreds);
      clearSavedSessions();
      window.location.reload();
    });

    addPreActivationCellPills(triggerActivate, kernel);

    if (hasSavedSession()) {
      activateThebe(ui);
    }
  });
})();
