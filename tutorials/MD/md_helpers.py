"""Mitchell Lab Molecular Dynamics Teaching Helpers.

Provides lightweight, browser-safe 3D molecular & trajectory viewers (using 3Dmol.js
inside sandboxed HTML iframes so they render identically in static Reading Mode,
live Thebe 0.9 cells, and JupyterLab 4) plus a peptide builder that converts any
student's name into an OpenMM-ready `.pdb` file.
"""

from __future__ import annotations

import html as _html
import io
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    from IPython.display import HTML
except ImportError:  # pragma: no cover

    class HTML(str):  # type: ignore[no-redef]
        """Fallback HTML container when IPython is not installed."""


AMINO_ACID_INFO: dict[str, tuple[str, str, str]] = {
    "A": ("ALA", "Alanine", "Hydrophobic (small, α-helix former)"),
    "C": ("CYS", "Cysteine", "Polar (forms disulphide bonds)"),
    "D": ("ASP", "Aspartate", "Negatively charged (acidic)"),
    "E": ("GLU", "Glutamate", "Negatively charged (acidic)"),
    "F": ("PHE", "Phenylalanine", "Hydrophobic (aromatic)"),
    "G": ("GLY", "Glycine", "Special (no sidechain, very flexible)"),
    "H": ("HIS", "Histidine", "Polar / positively charged"),
    "I": ("ILE", "Isoleucine", "Hydrophobic (branched)"),
    "K": ("LYS", "Lysine", "Positively charged (basic)"),
    "L": ("LEU", "Leucine", "Hydrophobic (α-helix former)"),
    "M": ("MET", "Methionine", "Hydrophobic (sulphur-containing)"),
    "N": ("ASN", "Asparagine", "Polar (uncharged)"),
    "P": ("PRO", "Proline", "Special (rigid ring, helix breaker)"),
    "Q": ("GLN", "Glutamine", "Polar (uncharged)"),
    "R": ("ARG", "Arginine", "Positively charged (basic)"),
    "S": ("SER", "Serine", "Polar (hydroxyl group)"),
    "T": ("THR", "Threonine", "Polar (hydroxyl group)"),
    "V": ("VAL", "Valine", "Hydrophobic (β-sheet former)"),
    "W": ("TRP", "Tryptophan", "Hydrophobic (bulky aromatic)"),
    "Y": ("TYR", "Tyrosine", "Polar / aromatic"),
}

_3DMOL_LOADER_JS = """
function load3Dmol(onReady, onFail) {
  if (window.$3Dmol) { onReady(); return; }
  var urls = [
    "https://3dmol.org/build/3Dmol-min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.4.2/3Dmol-min.js",
    "https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js"
  ];
  var idx = 0;
  function tryNext() {
    if (idx >= urls.length) { onFail(); return; }
    var s = document.createElement("script");
    s.src = urls[idx++];
    s.async = true;
    s.onload = function() {
      if (window.$3Dmol) onReady(); else tryNext();
    };
    s.onerror = tryNext;
    document.head.appendChild(s);
  }
  tryNext();
}
""".strip()

_VIEWER_BASE_CSS = """
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; width: 100%; height: 100%;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #ffffff; color: #0f172a; overflow: hidden;
}
.wrap { display: flex; flex-direction: column; width: 100%; height: 100%; }
.bar {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 6px; padding: 7px 10px;
  background: #f8fafc; border-bottom: 1px solid #e2e8f0; font-size: 12px;
}
.grp { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.title { font-weight: 700; color: #0f172a; margin-right: 4px; }
.btn {
  padding: 3px 8px; border-radius: 6px; border: 1px solid #cbd5e1;
  background: #ffffff; color: #1e293b; font-size: 11.5px; font-weight: 600;
  cursor: pointer; line-height: 1.3;
}
.btn:hover { background: #eff6ff; border-color: #93c5fd; color: #1d4ed8; }
.btn.active { background: #1d4ed8; border-color: #1d4ed8; color: #ffffff; }
.btn.play { background: #0f766e; border-color: #0f766e; color: #ffffff; min-width: 72px; }
.btn.play:hover { background: #115e59; color: #ffffff; }
select.ctrl {
  padding: 3px 6px; border-radius: 6px; border: 1px solid #cbd5e1;
  background: #ffffff; color: #1e293b; font-size: 11.5px; font-weight: 600;
}
.stage { position: relative; flex: 1 1 auto; width: 100%; min-height: 260px; background: #ffffff; }
.hint {
  position: absolute; bottom: 8px; right: 10px; z-index: 10;
  background: rgba(255,255,255,0.88); border: 1px solid #e2e8f0;
  border-radius: 6px; padding: 2px 8px; font-size: 11px; color: #475569;
  pointer-events: none;
}
.scrub-bar {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 12px;
}
.scrub-bar input[type=range] { flex: 1 1 auto; accent-color: #1d4ed8; cursor: pointer; }
.frame-label { font-variant-numeric: tabular-nums; font-weight: 600; color: #334155; min-width: 140px; text-align: right; }
.fallback {
  display: flex; align-items: center; justify-content: center; height: 100%;
  color: #64748b; font-size: 13px; padding: 1rem; text-align: center;
}
""".strip()


def _filter_pdb_text(pdb_path: str | Path, show_water: bool = False) -> str:
    """Read a PDB file, optionally stripping water (HOH/WAT/TIP3) records for fast browser rendering."""
    water_res = {"HOH", "WAT", "TIP3", "SOL"}
    kept: list[str] = []
    with open(pdb_path, "r", encoding="utf-8", errors="replace") as fp:
        for line in fp:
            rec = line[:6].strip()
            if rec in ("ATOM", "HETATM"):
                resname = line[17:20].strip()
                if not show_water and resname in water_res:
                    continue
                kept.append(line)
            elif rec in ("TER", "END", "MODEL", "ENDMDL", "HELIX", "SHEET"):
                kept.append(line)
    return "".join(kept)


def _iframe_html(srcdoc: str, height: int) -> HTML:
    escaped = _html.escape(srcdoc, quote=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return HTML(
            f'<iframe srcdoc="{escaped}" '
            f'style="width:100%;height:{int(height)}px;border:1px solid #cbd5e1;'
            f'border-radius:10px;background:#ffffff;display:block;" '
            f'loading="lazy" sandbox="allow-scripts allow-same-origin"></iframe>'
        )


def view_structure(
    pdb_file: str | Path,
    style: str = "cartoon",
    color: str = "spectrum",
    show_water: bool = False,
    title: str | None = None,
    height: int = 440,
    highlight_residues: Iterable[int] | None = None,
    highlight_labels: dict[int, str] | None = None,
) -> HTML:
    """Display a PDB structure in an interactive 3Dmol.js viewer.

    Supports ``color="spectrum"``, ``color="ss"``, ``color="element"``, and
    ``color="plddt"`` (official AlphaFold pLDDT confidence colour scale read
    from the PDB B-factor column). Optionally highlights specific residue
    numbers (e.g. clinical mutation sites) as magenta sticks + spheres with
    3D callout labels.

    Works in static Jupyter Book Reading Mode, live Thebe cells, and JupyterLab.
    """
    pdb_path = Path(pdb_file)
    pdb_text = _filter_pdb_text(pdb_path, show_water=show_water)
    label = title or pdb_path.name
    if not show_water and "water" in pdb_path.name.lower():
        label += " (protein shown; solvent hidden for clarity)"

    hl_res = [int(r) for r in (highlight_residues or [])]
    hl_lbl = {str(int(k)): str(v) for k, v in (highlight_labels or {}).items()}

    plddt_legend_css = """
.plddt-legend {
  display: none; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 5px 10px; background: #f8fafc; border-top: 1px solid #e2e8f0;
  font-size: 11px; color: #334155;
}
.plddt-legend.show { display: flex; }
.plddt-chip { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }
.plddt-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; border: 1px solid rgba(0,0,0,0.12); }
""".strip()

    srcdoc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{_VIEWER_BASE_CSS}\n{plddt_legend_css}</style></head>
<body>
<div class="wrap">
  <div class="bar">
    <div class="grp">
      <span class="title">{_html.escape(label)}</span>
    </div>
    <div class="grp">
      <button class="btn" data-style="cartoon">Cartoon</button>
      <button class="btn" data-style="cartoon+stick">Cartoon + Sticks</button>
      <button class="btn" data-style="stick">Sticks</button>
      <button class="btn" data-style="sphere">Spheres</button>
      <select class="ctrl" id="colorSel" aria-label="Colour scheme">
        <option value="spectrum">Rainbow (N→C)</option>
        <option value="plddt">AlphaFold pLDDT</option>
        <option value="ss">Secondary Structure</option>
        <option value="element">Element</option>
      </select>
      <button class="btn" id="resetBtn">Reset View</button>
    </div>
  </div>
  <div class="stage" id="viewer">
    <div class="fallback" id="loading">Loading interactive 3D molecular viewer…</div>
    <div class="hint">Drag to rotate · Scroll to zoom · Right-drag to pan</div>
  </div>
  <div class="plddt-legend" id="plddtLegend">
    <strong>AlphaFold pLDDT:</strong>
    <span class="plddt-chip"><span class="plddt-dot" style="background:#0053d6"></span>Very high (&gt;90)</span>
    <span class="plddt-chip"><span class="plddt-dot" style="background:#65cbf3"></span>Confident (70–90)</span>
    <span class="plddt-chip"><span class="plddt-dot" style="background:#ffdb13"></span>Low (50–70)</span>
    <span class="plddt-chip"><span class="plddt-dot" style="background:#ff7d45"></span>Very low (&lt;50)</span>
  </div>
</div>
<script>
{_3DMOL_LOADER_JS}
var PDB_DATA = {json.dumps(pdb_text)};
var INIT_STYLE = {json.dumps(style)};
var INIT_COLOR = {json.dumps(color)};
var HL_RES = {json.dumps(hl_res)};
var HL_LABELS = {json.dumps(hl_lbl)};
var viewer = null;
var curStyle = INIT_STYLE;
var curColor = INIT_COLOR;

function plddtColor(atom) {{
  var b = atom.b || 0;
  if (b >= 90) return "#0053d6";
  if (b >= 70) return "#65cbf3";
  if (b >= 50) return "#ffdb13";
  return "#ff7d45";
}}

function applyStyle() {{
  if (!viewer) return;
  viewer.setStyle({{}}, {{}});
  viewer.removeAllLabels();
  var colorSpec = curColor === "spectrum" ? {{color: "spectrum"}}
                : curColor === "plddt" ? {{colorfunc: plddtColor}}
                : curColor === "ss" ? {{colorfunc: function(atom) {{
                    if (atom.ss === "h") return "#2563eb";
                    if (atom.ss === "s") return "#ea580c";
                    return "#64748b";
                  }}}}
                : {{colorscheme: "Jmol"}};
  var protSel = {{not: {{resn: ["HOH", "WAT", "TIP3", "SOL"]}}}};
  if (curStyle === "cartoon") {{
    viewer.setStyle(protSel, {{cartoon: colorSpec}});
  }} else if (curStyle === "cartoon+stick") {{
    viewer.setStyle(protSel, {{cartoon: Object.assign({{opacity: 0.85}}, colorSpec), stick: {{radius: 0.14, colorscheme: "Jmol"}}}});
  }} else if (curStyle === "stick") {{
    viewer.setStyle(protSel, {{stick: curColor === "plddt" ? {{colorfunc: plddtColor, radius: 0.18}} : curColor === "spectrum" ? {{color: "spectrum", radius: 0.18}} : {{colorscheme: "Jmol", radius: 0.18}}}});
  }} else if (curStyle === "sphere") {{
    viewer.setStyle(protSel, {{sphere: curColor === "plddt" ? {{colorfunc: plddtColor, scale: 0.85}} : curColor === "spectrum" ? {{color: "spectrum", scale: 0.85}} : {{colorscheme: "Jmol", scale: 0.85}}}});
  }}
  viewer.setStyle({{resn: ["HOH", "WAT", "TIP3", "SOL"]}}, {{sphere: {{color: "#38bdf8", radius: 0.25, opacity: 0.45}}}});
  if (HL_RES.length > 0) {{
    viewer.addStyle({{resi: HL_RES}}, {{stick: {{color: "#db2777", radius: 0.26}}, sphere: {{color: "#db2777", radius: 0.42}}}});
    HL_RES.forEach(function(r) {{
      var lbl = HL_LABELS[String(r)] || ("Residue " + r);
      viewer.addLabel(lbl, {{
        backgroundColor: "#be185d", fontColor: "#ffffff", fontSize: 12,
        backgroundOpacity: 0.9, borderRadius: 4, inFront: true
      }}, {{resi: r, atom: "CA"}});
    }});
  }}
  viewer.render();
  document.querySelectorAll("[data-style]").forEach(function(b) {{
    b.classList.toggle("active", b.getAttribute("data-style") === curStyle);
  }});
  document.getElementById("colorSel").value = curColor;
  var leg = document.getElementById("plddtLegend");
  if (leg) leg.classList.toggle("show", curColor === "plddt");
}}

load3Dmol(function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.remove();
  viewer = $3Dmol.createViewer(document.getElementById("viewer"), {{backgroundColor: "white"}});
  viewer.addModel(PDB_DATA, "pdb");
  applyStyle();
  viewer.zoomTo();
  viewer.render();
}}, function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.textContent = "Interactive 3D viewer requires internet access in your browser to load 3Dmol.js.";
}});

document.querySelectorAll("[data-style]").forEach(function(btn) {{
  btn.addEventListener("click", function() {{
    curStyle = btn.getAttribute("data-style");
    applyStyle();
  }});
}});
document.getElementById("colorSel").addEventListener("change", function(e) {{
  curColor = e.target.value;
  applyStyle();
}});
document.getElementById("resetBtn").addEventListener("click", function() {{
  if (viewer) {{ viewer.zoomTo(); viewer.render(); }}
}});
</script>
</body></html>"""
    return _iframe_html(srcdoc, height=height)


def _trajectory_to_multimodel_pdb(
    pdb_file: str | Path,
    traj_file: str | Path,
    stride: int = 2,
    max_frames: int = 60,
    include_hydrogens: bool = False,
) -> tuple[str, list[int], int]:
    """Export centered MD trajectory frames to a compact multi-model PDB string."""
    import MDAnalysis as mda

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u = mda.Universe(str(pdb_file), str(traj_file))
        n_total = len(u.trajectory)
        if n_total == 0:
            raise ValueError(f"Trajectory {traj_file} contains 0 frames.")

        # Automatically widen stride if trajectory has many frames so HTML stays fast
        eff_stride = max(1, int(stride))
        indices = list(range(0, n_total, eff_stride))
        if (n_total - 1) not in indices:
            indices.append(n_total - 1)
        if len(indices) > max_frames:
            indices = sorted(
                set(np.linspace(0, n_total - 1, max_frames, dtype=int).tolist())
            )

        sel = "protein" if include_hydrogens else "protein and not name H* 1H* 2H* 3H*"
        atoms = u.select_atoms(sel)
        if len(atoms) == 0:
            atoms = u.atoms

        models: list[str] = []
        for model_idx, ts_idx in enumerate(indices, 1):
            u.trajectory[ts_idx]
            # Center molecule at origin so it stays centered in the 3D viewport
            coords = atoms.positions - atoms.center_of_geometry()
            lines = [f"MODEL     {model_idx:4d}\n"]
            for atom_i, (atom, xyz) in enumerate(zip(atoms, coords), 1):
                name = atom.name[:4]
                aname = f" {name:<3s}" if len(name) < 4 else name
                resname = (atom.resname or "UNK")[:3]
                chain = (getattr(atom, "chainID", "") or "A")[:1]
                resid = int(atom.resid) % 10000
                elem = (getattr(atom, "element", "") or atom.name[0])[:2]
                lines.append(
                    f"ATOM  {atom_i:5d} {aname} {resname:>3s} {chain:1s}{resid:4d}    "
                    f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {elem:>2s}\n"
                )
            lines.append("ENDMDL\n")
            models.append("".join(lines))

    return "".join(models), indices, n_total


def view_trajectory(
    pdb_file: str | Path,
    traj_file: str | Path,
    stride: int = 2,
    total_ps: float = 200.0,
    style: str = "cartoon+stick",
    include_hydrogens: bool = False,
    title: str | None = None,
    height: int = 480,
    highlight_residues: Iterable[int] | None = None,
) -> HTML:
    """Display an animated 3D MD trajectory with Play/Pause, scrubber, and speed controls."""
    pdb_path = Path(pdb_file)
    multimodel_pdb, frame_indices, n_total = _trajectory_to_multimodel_pdb(
        pdb_path, traj_file, stride=stride, include_hydrogens=include_hydrogens
    )
    n_shown = len(frame_indices)
    # Compute approximate simulation time (ps) per shown frame
    denom = max(1, n_total - 1)
    frame_times_ps = [round((idx / denom) * float(total_ps), 1) for idx in frame_indices]
    label = title or f"{pdb_path.stem} MD Trajectory ({n_shown} frames)"
    hl_res = [int(r) for r in (highlight_residues or [])]

    srcdoc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{_VIEWER_BASE_CSS}</style></head>
<body>
<div class="wrap">
  <div class="bar">
    <div class="grp">
      <span class="title">{_html.escape(label)}</span>
    </div>
    <div class="grp">
      <button class="btn" data-style="cartoon">Cartoon</button>
      <button class="btn" data-style="cartoon+stick">Cartoon + Sticks</button>
      <button class="btn" data-style="stick">Sticks</button>
      <button class="btn" data-speed="220">0.5×</button>
      <button class="btn active" data-speed="110">1×</button>
      <button class="btn" data-speed="55">2×</button>
      <button class="btn" id="resetBtn">Reset View</button>
    </div>
  </div>
  <div class="stage" id="viewer">
    <div class="fallback" id="loading">Loading interactive 3D trajectory player…</div>
    <div class="hint">Drag to rotate · Scroll to zoom · Click Play or drag slider</div>
  </div>
  <div class="scrub-bar">
    <button class="btn play" id="playBtn">▶ Play</button>
    <input type="range" id="scrubber" min="0" max="{max(0, n_shown - 1)}" value="0" aria-label="Trajectory frame">
    <span class="frame-label" id="frameLabel">Frame 1 / {n_shown} ({frame_times_ps[0]} ps)</span>
  </div>
</div>
<script>
{_3DMOL_LOADER_JS}
var MULTIMODEL_PDB = {json.dumps(multimodel_pdb)};
var FRAME_TIMES = {json.dumps(frame_times_ps)};
var N_FRAMES = {n_shown};
var HL_RES = {json.dumps(hl_res)};
var curStyle = {json.dumps(style)};
var curFrame = 0;
var playing = false;
var timerId = null;
var frameDelay = 110;
var viewer = null;

var playBtn = document.getElementById("playBtn");
var scrubber = document.getElementById("scrubber");
var frameLabel = document.getElementById("frameLabel");

function styleFor(st) {{
  if (st === "cartoon") return {{cartoon: {{color: "spectrum"}}}};
  if (st === "stick") return {{stick: {{color: "spectrum", radius: 0.16}}}};
  return {{cartoon: {{color: "spectrum", opacity: 0.88}}, stick: {{radius: 0.12, colorscheme: "Jmol"}}}};
}}

function applyStyle() {{
  if (!viewer) return;
  viewer.setStyle({{}}, styleFor(curStyle));
  if (HL_RES.length > 0) {{
    viewer.addStyle({{resi: HL_RES}}, {{stick: {{color: "#db2777", radius: 0.25}}, sphere: {{color: "#db2777", radius: 0.40}}}});
  }}
  viewer.render();
  document.querySelectorAll("[data-style]").forEach(function(b) {{
    b.classList.toggle("active", b.getAttribute("data-style") === curStyle);
  }});
}}

function showFrame(idx) {{
  curFrame = ((idx % N_FRAMES) + N_FRAMES) % N_FRAMES;
  scrubber.value = String(curFrame);
  frameLabel.textContent = "Frame " + (curFrame + 1) + " / " + N_FRAMES + " (" + FRAME_TIMES[curFrame] + " ps)";
  if (viewer) {{
    viewer.setFrame(curFrame);
    viewer.render();
  }}
}}

function stopPlay() {{
  playing = false;
  if (timerId !== null) {{ clearInterval(timerId); timerId = null; }}
  playBtn.textContent = "▶ Play";
}}

function startPlay() {{
  if (N_FRAMES <= 1) return;
  stopPlay();
  playing = true;
  playBtn.textContent = "⏸ Pause";
  timerId = setInterval(function() {{
    showFrame(curFrame + 1);
  }}, frameDelay);
}}

load3Dmol(function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.remove();
  viewer = $3Dmol.createViewer(document.getElementById("viewer"), {{backgroundColor: "white"}});
  viewer.addModelsAsFrames(MULTIMODEL_PDB, "pdb");
  applyStyle();
  showFrame(0);
  viewer.zoomTo();
  viewer.render();
}}, function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.textContent = "Interactive 3D trajectory player requires internet access in your browser to load 3Dmol.js.";
}});

playBtn.addEventListener("click", function() {{
  if (playing) stopPlay(); else startPlay();
}});
scrubber.addEventListener("input", function() {{
  stopPlay();
  showFrame(parseInt(scrubber.value, 10) || 0);
}});
document.querySelectorAll("[data-style]").forEach(function(btn) {{
  btn.addEventListener("click", function() {{
    curStyle = btn.getAttribute("data-style");
    applyStyle();
  }});
}});
document.querySelectorAll("[data-speed]").forEach(function(btn) {{
  btn.addEventListener("click", function() {{
    frameDelay = parseInt(btn.getAttribute("data-speed"), 10) || 110;
    document.querySelectorAll("[data-speed]").forEach(function(b) {{
      b.classList.toggle("active", b === btn);
    }});
    if (playing) startPlay();
  }});
}});
document.getElementById("resetBtn").addEventListener("click", function() {{
  if (viewer) {{ viewer.zoomTo(); viewer.render(); }}
}});
</script>
</body></html>"""
    return _iframe_html(srcdoc, height=height)


def build_name_peptide(
    name: str,
    out_path: str | Path | None = None,
    forcefield: str = "amber10.xml",
    min_residues: int = 4,
) -> tuple[str, str, int]:
    """Convert any student name into an OpenMM-ready polypeptide `.pdb` file.

    Keeps valid 1-letter amino acid codes (`ACDEFGHIKLMNPQRSTVWY`), reports any
    non-amino-acid letters (`B, J, O, U, X, Z`), constructs an extended chain
    with `PeptideBuilder`, and adds force-field-compatible hydrogens using OpenMM
    `Modeller` so the resulting PDB simulates cleanly with `amber10.xml`.

    Returns `(pdb_path, sequence_1letter, num_residues)`.
    """
    import PeptideBuilder
    from Bio.PDB import PDBIO
    from openmm.app import ForceField, Modeller, PDBFile

    letters_only = [ch for ch in name.upper() if ch.isalpha()]
    valid_seq = [ch for ch in letters_only if ch in AMINO_ACID_INFO]
    skipped = [ch for ch in letters_only if ch not in AMINO_ACID_INFO]

    if not valid_seq:
        raise ValueError(
            f"None of the letters in {name!r} match the 20 standard 1-letter amino acid "
            "codes (ACDEFGHIKLMNPQRSTVWY). Try including your surname too!"
        )

    padded = False
    while len(valid_seq) < min_residues:
        valid_seq.append("A")
        padded = True

    sequence = "".join(valid_seq)
    if out_path is None:
        out_path = Path("data") / f"peptide_{sequence}.pdb"
    else:
        out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build extended polypeptide backbone + sidechains
    structure = PeptideBuilder.initialize_res(sequence[0])
    for aa in sequence[1:]:
        PeptideBuilder.add_residue(structure, aa)
    PeptideBuilder.add_terminal_OXT(structure)

    with tempfile.NamedTemporaryFile(suffix=".pdb", mode="w", delete=False) as tmp:
        raw_pdb_path = tmp.name

    try:
        io_writer = PDBIO()
        io_writer.set_structure(structure)
        io_writer.save(raw_pdb_path)

        # Add exact amber10-compatible hydrogens via OpenMM Modeller
        ff = ForceField(forcefield)
        pdb_raw = PDBFile(raw_pdb_path)
        modeller = Modeller(pdb_raw.topology, pdb_raw.positions)
        modeller.addHydrogens(ff)
        with open(out_path, "w", encoding="utf-8") as fp:
            PDBFile.writeFile(modeller.topology, modeller.positions, fp)
    finally:
        if os.path.exists(raw_pdb_path):
            os.remove(raw_pdb_path)

    print(f"Input name        : {name}")
    if skipped:
        print(
            f"Skipped letters   : {', '.join(skipped)} "
            "(not among the 20 standard amino acids: B, J, O, U, X, Z have no standard residue)"
        )
    if padded:
        print(
            f"Note              : Padded short sequence with Alanine (A) to {min_residues} residues "
            "so backbone dihedral angles can be analysed."
        )
    print(f"Peptide sequence  : {sequence} ({len(sequence)} residues, {len(modeller.positions)} atoms)")
    print(f"Saved PDB file    : {out_path}")
    print("\nResidue breakdown:")
    for i, aa in enumerate(sequence, 1):
        code3, full_name, prop = AMINO_ACID_INFO[aa]
        print(f"  {i:2d}. {aa} ({code3}) — {full_name:14s} [{prop}]")

    return str(out_path), sequence, len(sequence)


AA3_TO_AA1: dict[str, str] = {info[0]: aa1 for aa1, info in AMINO_ACID_INFO.items()}


def load_plddt(pdb_file: str | Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Read per-residue AlphaFold pLDDT confidence scores from a PDB file's B-factor column.

    Returns ``(resids, resnames, plddt)`` for all Cα atoms in residue order.
    """
    resids: list[int] = []
    resnames: list[str] = []
    plddt: list[float] = []
    seen: set[int] = set()
    with open(pdb_file, "r", encoding="utf-8", errors="replace") as fp:
        for line in fp:
            if line[:6].strip() != "ATOM":
                continue
            if line[12:16].strip() != "CA":
                continue
            alt = line[16]
            if alt not in (" ", "A"):
                continue
            rid = int(line[22:26])
            if rid in seen:
                continue
            seen.add(rid)
            resids.append(rid)
            resnames.append(line[17:20].strip())
            plddt.append(float(line[60:66]))
    return np.asarray(resids, dtype=int), resnames, np.asarray(plddt, dtype=float)


def load_pae(pae_json_file: str | Path) -> np.ndarray:
    """Load an AlphaFold Predicted Aligned Error (PAE) matrix (in Å) from an AFDB JSON file."""
    with open(pae_json_file, "r", encoding="utf-8") as fp:
        raw = json.load(fp)
    entry = raw[0] if isinstance(raw, list) else raw
    if "predicted_aligned_error" in entry:
        return np.asarray(entry["predicted_aligned_error"], dtype=float)
    if "pae" in entry:
        return np.asarray(entry["pae"], dtype=float)
    raise KeyError(f"Could not find 'predicted_aligned_error' in {pae_json_file}")


def load_alphamissense(
    csv_file: str | Path,
) -> tuple[dict[str, tuple[float, str]], dict[int, float]]:
    """Parse an EMBL-EBI AlphaFold DB AlphaMissense substitution table (`.csv`).

    Returns:
      - ``by_variant``: mapping e.g. ``"L252P" -> (0.9974, "LPath")``
      - ``mean_by_resid``: mapping residue number ``int -> mean pathogenicity (0–1)``
    """
    import csv

    by_variant: dict[str, tuple[float, str]] = {}
    scores_by_res: dict[int, list[float]] = {}
    with open(csv_file, "r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            var = row["protein_variant"].strip()
            score = float(row["am_pathogenicity"])
            am_class = row["am_class"].strip()
            by_variant[var] = (score, am_class)
            rid = int(var[1:-1])
            scores_by_res.setdefault(rid, []).append(score)
    mean_by_resid = {rid: float(np.mean(vals)) for rid, vals in scores_by_res.items()}
    return by_variant, mean_by_resid


def _kabsch_align(mobile: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(rotation_matrix, mobile_center, target_center)`` aligning ``mobile`` onto ``target``."""
    m_cen = mobile.mean(axis=0)
    t_cen = target.mean(axis=0)
    h_mat = (mobile - m_cen).T @ (target - t_cen)
    u_mat, _s, vt_mat = np.linalg.svd(h_mat)
    rot = vt_mat.T @ u_mat.T
    if np.linalg.det(rot) < 0:
        vt_mat[-1, :] *= -1.0
        rot = vt_mat.T @ u_mat.T
    return rot, m_cen, t_cen


def _transform_pdb_text(pdb_path: str | Path, rot: np.ndarray, m_cen: np.ndarray, t_cen: np.ndarray) -> str:
    """Apply a rigid-body Kabsch transform to all ATOM coordinates of a PDB file."""
    out: list[str] = []
    with open(pdb_path, "r", encoding="utf-8", errors="replace") as fp:
        for line in fp:
            rec = line[:6].strip()
            if rec == "ATOM":
                xyz = np.array(
                    [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                    dtype=float,
                )
                new_xyz = (xyz - m_cen) @ rot.T + t_cen
                out.append(
                    f"{line[:30]}{new_xyz[0]:8.3f}{new_xyz[1]:8.3f}{new_xyz[2]:8.3f}{line[54:]}"
                )
            elif rec in ("TER", "END"):
                out.append(line)
    return "".join(out)


def view_superposition(
    pdb_ref: str | Path,
    pdb_mobile: str | Path,
    ref_label: str = "Reference (AlphaFold)",
    mobile_label: str = "Comparison (Experimental)",
    ref_color: str = "#2563eb",
    mobile_color: str = "#ea580c",
    align_resids: Iterable[int] | None = None,
    highlight_residues: Iterable[int] | None = None,
    highlight_labels: dict[int, str] | None = None,
    title: str | None = None,
    height: int = 460,
) -> HTML:
    """Superpose ``pdb_mobile`` onto ``pdb_ref`` on common Cα atoms and display both in 3D.

    Prints the aligned Cα RMSD (Å) and displays both models overlaid in an
    interactive 3Dmol.js viewer with legend chips and optional mutation highlights.
    """
    import MDAnalysis as mda

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u_ref = mda.Universe(str(pdb_ref))
        u_mob = mda.Universe(str(pdb_mobile))
        ref_ca = {
            int(a.resid): a.position.copy()
            for a in u_ref.select_atoms("protein and name CA")
        }
        mob_ca = {
            int(a.resid): a.position.copy()
            for a in u_mob.select_atoms("protein and name CA")
        }

    common = sorted(set(ref_ca) & set(mob_ca))
    if align_resids is not None:
        allowed = {int(r) for r in align_resids}
        fit_res = [r for r in common if r in allowed]
    else:
        fit_res = common
    if len(fit_res) < 3:
        raise ValueError("Need at least 3 shared Cα residues to superpose two structures.")

    ref_pts = np.asarray([ref_ca[r] for r in fit_res], dtype=float)
    mob_pts = np.asarray([mob_ca[r] for r in fit_res], dtype=float)
    rot, m_cen, t_cen = _kabsch_align(mob_pts, ref_pts)

    # Compute RMSD across all shared Cα atoms after fitting on fit_res
    all_ref = np.asarray([ref_ca[r] for r in common], dtype=float)
    all_mob_rot = (np.asarray([mob_ca[r] for r in common], dtype=float) - m_cen) @ rot.T + t_cen
    rmsd_all = float(np.sqrt(np.mean(np.sum((all_ref - all_mob_rot) ** 2, axis=1))))

    ref_text = _filter_pdb_text(pdb_ref, show_water=False)
    mob_text = _transform_pdb_text(pdb_mobile, rot, m_cen, t_cen)

    hl_res = [int(r) for r in (highlight_residues or [])]
    hl_lbl = {str(int(k)): str(v) for k, v in (highlight_labels or {}).items()}
    hdr = title or f"{ref_label} vs {mobile_label} (Cα RMSD = {rmsd_all:.2f} Å)"

    legend_css = """
.sup-legend {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  padding: 5px 10px; background: #f8fafc; border-top: 1px solid #e2e8f0;
  font-size: 11.5px; color: #334155;
}
.sup-chip { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; }
.sup-dot { width: 12px; height: 10px; border-radius: 3px; display: inline-block; }
""".strip()

    srcdoc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{_VIEWER_BASE_CSS}\n{legend_css}</style></head>
<body>
<div class="wrap">
  <div class="bar">
    <div class="grp"><span class="title">{_html.escape(hdr)}</span></div>
    <div class="grp">
      <button class="btn active" id="toggleRef">Toggle Model 1</button>
      <button class="btn active" id="toggleMob">Toggle Model 2</button>
      <button class="btn" id="resetBtn">Reset View</button>
    </div>
  </div>
  <div class="stage" id="viewer">
    <div class="fallback" id="loading">Loading interactive 3D superposition viewer…</div>
    <div class="hint">Drag to rotate · Scroll to zoom · Right-drag to pan</div>
  </div>
  <div class="sup-legend">
    <span class="sup-chip"><span class="sup-dot" style="background:{_html.escape(ref_color)}"></span>{_html.escape(ref_label)}</span>
    <span class="sup-chip"><span class="sup-dot" style="background:{_html.escape(mobile_color)}"></span>{_html.escape(mobile_label)}</span>
    <span>Shared Cα atoms: <strong>{len(common)}</strong> · Overall Cα RMSD: <strong>{rmsd_all:.2f} Å</strong></span>
  </div>
</div>
<script>
{_3DMOL_LOADER_JS}
var REF_PDB = {json.dumps(ref_text)};
var MOB_PDB = {json.dumps(mob_text)};
var REF_COL = {json.dumps(ref_color)};
var MOB_COL = {json.dumps(mobile_color)};
var HL_RES = {json.dumps(hl_res)};
var HL_LABELS = {json.dumps(hl_lbl)};
var showRef = true;
var showMob = true;
var viewer = null;

function applyStyles() {{
  if (!viewer) return;
  viewer.setStyle({{}}, {{}});
  viewer.removeAllLabels();
  if (showRef) {{
    viewer.setStyle({{model: 0}}, {{cartoon: {{color: REF_COL, opacity: 0.92}}}});
  }}
  if (showMob) {{
    viewer.setStyle({{model: 1}}, {{cartoon: {{color: MOB_COL, opacity: 0.92}}}});
  }}
  if (HL_RES.length > 0 && showRef) {{
    viewer.addStyle({{model: 0, resi: HL_RES}}, {{stick: {{color: "#db2777", radius: 0.26}}, sphere: {{color: "#db2777", radius: 0.42}}}});
    HL_RES.forEach(function(r) {{
      var lbl = HL_LABELS[String(r)] || ("Residue " + r);
      viewer.addLabel(lbl, {{
        backgroundColor: "#be185d", fontColor: "#ffffff", fontSize: 12,
        backgroundOpacity: 0.9, borderRadius: 4, inFront: true
      }}, {{model: 0, resi: r, atom: "CA"}});
    }});
  }}
  viewer.render();
  document.getElementById("toggleRef").classList.toggle("active", showRef);
  document.getElementById("toggleMob").classList.toggle("active", showMob);
}}

load3Dmol(function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.remove();
  viewer = $3Dmol.createViewer(document.getElementById("viewer"), {{backgroundColor: "white"}});
  viewer.addModel(REF_PDB, "pdb");
  viewer.addModel(MOB_PDB, "pdb");
  applyStyles();
  viewer.zoomTo();
  viewer.render();
}}, function() {{
  var ld = document.getElementById("loading");
  if (ld) ld.textContent = "Interactive 3D viewer requires internet access in your browser to load 3Dmol.js.";
}});

document.getElementById("toggleRef").addEventListener("click", function() {{ showRef = !showRef; applyStyles(); }});
document.getElementById("toggleMob").addEventListener("click", function() {{ showMob = !showMob; applyStyles(); }});
document.getElementById("resetBtn").addEventListener("click", function() {{ if (viewer) {{ viewer.zoomTo(); viewer.render(); }} }});
</script>
</body></html>"""
    return _iframe_html(srcdoc, height=height)


def mutate_structure(
    pdb_in: str | Path,
    resid: int,
    new_aa: str,
    out_pdb: str | Path | None = None,
    add_hydrogens: bool = False,
    forcefield: str = "amber10.xml",
    quiet: bool = False,
) -> str:
    """Introduce a single missense point mutation into a PDB file cleanly.

    Preserves the exact backbone ``(N, CA, C, O)`` and AlphaFold pLDDT B-factors
    while placing the mutant sidechain using ideal geometry superposed onto the
    residue's ``(N, CA, C)`` frame via Kabsch alignment. Optionally adds
    force-field hydrogens with OpenMM ``Modeller``.

    Returns the path to the saved mutant PDB file.
    """
    import PeptideBuilder

    aa1 = new_aa.strip().upper()
    if aa1 not in AMINO_ACID_INFO:
        raise ValueError(
            f"Unknown amino acid code {new_aa!r}. Use a standard 1-letter code: {''.join(AMINO_ACID_INFO)}"
        )
    new_res3, new_full, new_prop = AMINO_ACID_INFO[aa1]
    pdb_path = Path(pdb_in)

    # Build ideal tripeptide A-X-A to extract standard sidechain coordinates of X
    template_struct = PeptideBuilder.initialize_res("A")
    PeptideBuilder.add_residue(template_struct, aa1)
    PeptideBuilder.add_residue(template_struct, "A")
    tmpl_res = list(template_struct.get_residues())[1]
    tmpl_bb = np.asarray([tmpl_res[a].get_coord() for a in ("N", "CA", "C")], dtype=float)
    tmpl_sc = [
        (atom.get_name(), np.asarray(atom.get_coord(), dtype=float), atom.element)
        for atom in tmpl_res.get_atoms()
        if atom.get_name() not in ("N", "CA", "C", "O", "OXT")
    ]

    with open(pdb_path, "r", encoding="utf-8", errors="replace") as fp:
        lines = fp.readlines()

    tgt_bb_map: dict[str, np.ndarray] = {}
    tgt_line: str | None = None
    orig_res3 = ""
    for line in lines:
        if line[:6].strip() == "ATOM" and int(line[22:26]) == int(resid):
            aname = line[12:16].strip()
            if aname in ("N", "CA", "C"):
                tgt_bb_map[aname] = np.array(
                    [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                    dtype=float,
                )
            if tgt_line is None:
                tgt_line = line
                orig_res3 = line[17:20].strip()

    if len(tgt_bb_map) < 3 or tgt_line is None:
        raise ValueError(f"Residue {resid} (backbone N/CA/C) not found in {pdb_path}.")

    tgt_bb = np.asarray([tgt_bb_map["N"], tgt_bb_map["CA"], tgt_bb_map["C"]], dtype=float)
    rot, t_mean, g_mean = _kabsch_align(tmpl_bb, tgt_bb)

    out_lines: list[str] = []
    inserted = False
    serial = 1
    for line in lines:
        if line[:6].strip() == "ATOM":
            r = int(line[22:26])
            aname = line[12:16].strip()
            if r == int(resid):
                if aname in ("N", "CA", "C", "O", "OXT"):
                    out_lines.append(
                        f"ATOM  {serial:5d}{line[11:17]}{new_res3:>3s}{line[20:]}"
                    )
                    serial += 1
                    if aname == "O" and not inserted:
                        chain = tgt_line[21]
                        bfac = tgt_line[60:66]
                        for sc_name, sc_xyz, elem in tmpl_sc:
                            xyz = (sc_xyz - t_mean) @ rot.T + g_mean
                            an_fmt = f" {sc_name:<3s}" if len(sc_name) < 4 else sc_name[:4]
                            el_fmt = (elem or sc_name[0])[:2]
                            out_lines.append(
                                f"ATOM  {serial:5d} {an_fmt} {new_res3:>3s} {chain}{int(resid):4d}    "
                                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00{bfac}          {el_fmt:>2s}\n"
                            )
                            serial += 1
                        inserted = True
                continue
            out_lines.append(f"ATOM  {serial:5d}{line[11:]}")
            serial += 1
        else:
            out_lines.append(line)

    orig_aa1 = AA3_TO_AA1.get(orig_res3, "?")
    if out_pdb is None:
        out_path = pdb_path.parent / f"{pdb_path.stem}_{orig_aa1}{int(resid)}{aa1}.pdb"
    else:
        out_path = Path(out_pdb)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as fp:
        fp.writelines(out_lines)

    if add_hydrogens:
        prepare_for_openmm(out_path, out_pdb=out_path, forcefield=forcefield)

    if not quiet:
        orig_full, orig_prop = AMINO_ACID_INFO.get(orig_aa1, (orig_res3, orig_res3, ""))[1:]
        print(f"Mutated residue   : {orig_res3} {resid} ({orig_aa1}) → {new_res3} {resid} ({aa1})")
        print(f"Wild-type         : {orig_full} [{orig_prop}]")
        print(f"Mutant            : {new_full} [{new_prop}]")
        print(f"Saved mutant PDB  : {out_path}")

    return str(out_path)


def prepare_for_openmm(
    structure_in: str | Path,
    out_pdb: str | Path | None = None,
    forcefield: str = "amber10.xml",
) -> str:
    """Prepare an AlphaFold `.pdb` or `.cif` file for OpenMM by adding missing hydrogens.

    Works seamlessly on both AlphaFold DB `.pdb` files and AlphaFold Server `.cif` files.
    """
    from openmm.app import ForceField, Modeller, PDBFile, PDBxFile

    in_path = Path(structure_in)
    if in_path.suffix.lower() in (".cif", ".mmcif"):
        loaded = PDBxFile(str(in_path))
    else:
        loaded = PDBFile(str(in_path))

    ff = ForceField(forcefield)
    modeller = Modeller(loaded.topology, loaded.positions)
    modeller.addHydrogens(ff)

    out_path = Path(out_pdb) if out_pdb is not None else in_path.with_name(f"{in_path.stem}_openmm.pdb")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        PDBFile.writeFile(modeller.topology, modeller.positions, fp, keepIds=True)
    return str(out_path)

