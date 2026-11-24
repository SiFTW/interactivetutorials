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
) -> HTML:
    """Display a PDB structure in an interactive 3Dmol.js viewer.

    Works in static Jupyter Book Reading Mode, live Thebe cells, and JupyterLab.
    """
    pdb_path = Path(pdb_file)
    pdb_text = _filter_pdb_text(pdb_path, show_water=show_water)
    label = title or pdb_path.name
    if not show_water and "water" in pdb_path.name.lower():
        label += " (protein shown; solvent hidden for clarity)"

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
      <button class="btn" data-style="sphere">Spheres</button>
      <select class="ctrl" id="colorSel" aria-label="Colour scheme">
        <option value="spectrum">Rainbow (N→C)</option>
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
</div>
<script>
{_3DMOL_LOADER_JS}
var PDB_DATA = {json.dumps(pdb_text)};
var INIT_STYLE = {json.dumps(style)};
var INIT_COLOR = {json.dumps(color)};
var viewer = null;
var curStyle = INIT_STYLE;
var curColor = INIT_COLOR;

function applyStyle() {{
  if (!viewer) return;
  viewer.setStyle({{}}, {{}});
  var colorSpec = curColor === "spectrum" ? {{color: "spectrum"}}
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
    viewer.setStyle(protSel, {{stick: curColor === "spectrum" ? {{color: "spectrum", radius: 0.18}} : {{colorscheme: "Jmol", radius: 0.18}}}});
  }} else if (curStyle === "sphere") {{
    viewer.setStyle(protSel, {{sphere: curColor === "spectrum" ? {{color: "spectrum", scale: 0.85}} : {{colorscheme: "Jmol", scale: 0.85}}}});
  }}
  viewer.setStyle({{resn: ["HOH", "WAT", "TIP3", "SOL"]}}, {{sphere: {{color: "#38bdf8", radius: 0.25, opacity: 0.45}}}});
  viewer.render();
  document.querySelectorAll("[data-style]").forEach(function(b) {{
    b.classList.toggle("active", b.getAttribute("data-style") === curStyle);
  }});
  document.getElementById("colorSel").value = curColor;
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
