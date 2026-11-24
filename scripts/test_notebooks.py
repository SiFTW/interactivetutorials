#!/usr/bin/env python3
"""End-to-end Julia & Python notebook execution test suite for Mitchell Lab interactive books.

Executes every code cell of every `.ipynb` notebook in `book/` and `ssc/` sequentially
in an isolated Julia or Python process (matching how a student runs all cells in order
via Thebe or JupyterLab), verifying:
  1. For Julia notebooks:
     - Zero banned non-sysimage heavy package imports (prevents 2 GB container OOM crashes).
     - Every code cell parses cleanly with Julia's `Meta.parseall`.
     - Every code cell executes with zero uncaught exceptions in `Main` top-level scope.
     - Every `Plots.Plot` returned or passed to `display(...)` renders cleanly to SVG
       under headless GR (`GKSwstype=100`).
  2. For Python notebooks (e.g. Molecular Dynamics with OpenMM & MDAnalysis):
     - Every code cell parses cleanly with Python's `ast.parse`.
     - Every code cell executes sequentially in a shared global namespace with zero
       uncaught exceptions under headless Matplotlib (`MPLBACKEND=Agg`).

Uses only the Python 3 standard library so it runs cleanly both in GitHub Actions CI
and inside the `mitchell-lab/julia-tutorial-kernel` Docker container on 139.184.169.98.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BANNED_NON_SYSIMAGE_IMPORTS = (
    "StatsPlots",
    "JLD2",
    "FileIO",
    "Sundials",
    "BSON",
    "Distributions",
    "CairoMakie",
    "plotly(",
)

JULIA_RUNNER = r'''
struct HeadlessPlotDisplay <: AbstractDisplay end

function Base.display(::HeadlessPlotDisplay, x)
    if isdefined(Main, :Plots) && x isa Main.Plots.Plot
        show(IOBuffer(), MIME("image/svg+xml"), x)
        return nothing
    end
    throw(MethodError(display, (HeadlessPlotDisplay(), x)))
end

pushdisplay(HeadlessPlotDisplay())

const nb_label = ARGS[1]
const syntax_only = ARGS[2] == "1"
const cell_files = ARGS[3:end]

# Pass 1: Syntax check all cells up front
for (idx, path) in enumerate(cell_files)
    src = read(path, String)
    try
        Meta.parseall(src; filename="$(nb_label)::cell_$(idx)")
    catch err
        println(stderr, "SYNTAX ERROR in $(nb_label) code cell #$(idx):")
        showerror(stderr, err, catch_backtrace())
        println(stderr)
        exit(2)
    end
end

if syntax_only
    println("SYNTAX OK: $(nb_label) ($(length(cell_files)) code cells)")
    exit(0)
end

# Pass 2: Execute each code cell sequentially in Main top-level scope
for (idx, path) in enumerate(cell_files)
    src = read(path, String)
    t0 = time()
    try
        val = Base.include_string(Main, src, "$(nb_label)::cell_$(idx)")
        if val !== nothing && isdefined(Main, :Plots) && val isa Main.Plots.Plot
            show(IOBuffer(), MIME("image/svg+xml"), val)
        end
        dt = round(time() - t0; digits=2)
        println("  [OK] cell $(idx)/$(length(cell_files)) ($(dt)s)")
        flush(stdout)
    catch err
        println(stderr, "RUNTIME ERROR in $(nb_label) code cell #$(idx):")
        showerror(stderr, err, catch_backtrace())
        println(stderr)
        exit(3)
    end
end
'''

PYTHON_RUNNER = r'''
import ast
import sys
import time
import traceback

nb_label = sys.argv[1]
syntax_only = sys.argv[2] == "1"
cell_files = sys.argv[3:]

# Pass 1: Syntax check all cells up front
parsed = []
for idx, path in enumerate(cell_files, 1):
    with open(path, "r", encoding="utf-8") as fp:
        src = fp.read()
    try:
        tree = ast.parse(src, filename=f"{nb_label}::cell_{idx}")
        parsed.append((idx, src, tree))
    except SyntaxError:
        print(f"SYNTAX ERROR in {nb_label} code cell #{idx}:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)

if syntax_only:
    print(f"SYNTAX OK: {nb_label} ({len(cell_files)} code cells)")
    sys.exit(0)

# Pass 2: Execute each code cell sequentially in a shared global namespace
ns = {"__name__": "__main__"}
for idx, src, _tree in parsed:
    t0 = time.monotonic()
    try:
        code = compile(src, f"{nb_label}::cell_{idx}", "exec")
        exec(code, ns)
        dt = round(time.monotonic() - t0, 2)
        print(f"  [OK] cell {idx}/{len(cell_files)} ({dt}s)", flush=True)
    except Exception:
        print(f"RUNTIME ERROR in {nb_label} code cell #{idx}:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)
'''


def detect_notebook_language(nb: dict) -> str:
    """Return 'python' or 'julia' based on notebook kernelspec / language_info metadata."""
    meta = nb.get("metadata", {}) or {}
    ks = meta.get("kernelspec", {}) or {}
    lang_info = meta.get("language_info", {}) or {}
    lang = str(ks.get("language") or lang_info.get("name") or ks.get("name") or "").lower()
    if "python" in lang:
        return "python"
    return "julia"


def discover_notebooks(repo_dir: Path, filt: str | None) -> list[Path]:
    nbs: list[Path] = []
    for root_name in ("book", "ssc"):
        root = repo_dir / root_name
        if root.is_dir():
            nbs.extend(sorted(root.rglob("*.ipynb")))
    nbs = [p for p in nbs if ".ipynb_checkpoints" not in p.parts and "_build" not in p.parts]
    if filt:
        nbs = [p for p in nbs if filt in str(p.relative_to(repo_dir))]
    return nbs


def check_banned_imports(rel_path: str, code_cells: list[str]) -> list[str]:
    errors: list[str] = []
    for idx, src in enumerate(code_cells, 1):
        for lineno, raw_line in enumerate(src.splitlines(), 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for bad in BANNED_NON_SYSIMAGE_IMPORTS:
                if bad in stripped:
                    errors.append(
                        f"{rel_path} code cell #{idx} line {lineno}: banned non-sysimage token {bad!r} -> {stripped}"
                    )
    return errors


def prepare_workspace(repo_dir: Path, work_dir: Path) -> None:
    """Mirror the exact `/home/jovyan/work/` layout baked into Dockerfile.julia-kernel."""
    toy_src = repo_dir / "tutorials" / "toyModel"
    if toy_src.is_dir():
        for item in toy_src.iterdir():
            dst = work_dir / item.name
            if item.is_file():
                shutil.copy2(item, dst)
            elif item.is_dir() and item.name != "__pycache__":
                shutil.copytree(item, dst)

    for sub in ("MD", "NFkB", "apoptosis", "cellCycle"):
        src = repo_dir / "tutorials" / sub
        if src.is_dir():
            shutil.copytree(
                src,
                work_dir / sub,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )


def run_notebook(
    repo_dir: Path,
    nb_path: Path,
    nb_lang: str,
    julia_cmd: list[str],
    python_cmd: list[str],
    in_container_work: Path | None,
    syntax_only: bool,
    timeout_sec: int,
) -> tuple[bool, float, str]:
    rel = str(nb_path.relative_to(repo_dir))
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [
        "".join(cell.get("source", []))
        for cell in nb.get("cells", [])
        if cell.get("cell_type") == "code" and "".join(cell.get("source", [])).strip()
    ]

    if nb_lang == "julia":
        banned = check_banned_imports(rel, code_cells)
        if banned:
            return False, 0.0, "\n".join(banned)

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nbtest_") as td:
        td_path = Path(td)
        ext = "py" if nb_lang == "python" else "jl"
        runner_path = td_path / f"runner.{ext}"
        runner_path.write_text(
            PYTHON_RUNNER if nb_lang == "python" else JULIA_RUNNER,
            encoding="utf-8",
        )

        cell_paths: list[str] = []
        for idx, src in enumerate(code_cells, 1):
            cp = td_path / f"cell_{idx:02d}.{ext}"
            cp.write_text(src, encoding="utf-8")
            cell_paths.append(str(cp))

        if in_container_work is not None:
            cwd = in_container_work
        else:
            work_dir = td_path / "work"
            work_dir.mkdir()
            prepare_workspace(repo_dir, work_dir)
            cwd = work_dir

        env = os.environ.copy()
        env.setdefault("GKSwstype", "100")
        env.setdefault("PLOTS_DEFAULT_BACKEND", "GR")
        env.setdefault("MPLBACKEND", "Agg")
        env.setdefault("OPENMM_CPU_THREADS", "1")
        env.setdefault("OMP_NUM_THREADS", "1")

        runtime_cmd = python_cmd if nb_lang == "python" else julia_cmd
        cmd = [
            *runtime_cmd,
            str(runner_path),
            rel,
            "1" if syntax_only else "0",
            *cell_paths,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            dt = time.monotonic() - t0
            out = (exc.stdout or "") + "\n" + (exc.stderr or "")
            return False, dt, f"TIMEOUT after {timeout_sec}s\n{out}".strip()

        dt = time.monotonic() - t0
        combined = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
        return proc.returncode == 0, dt, combined


def _normalize_argv(argv: list[str]) -> list[str]:
    """Rewrite `--julia-args <val>` to `--julia-args=<val>` so argparse accepts values starting with `-`."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--julia-args" and i + 1 < len(argv):
            out.append(f"--julia-args={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute all interactive Julia & Python notebooks and fail on any cell error."
    )
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent), help="Path to repo root")
    parser.add_argument("--julia", default="julia", help="Path to julia binary")
    parser.add_argument(
        "--julia-args",
        default="",
        help="Extra flags passed to julia (e.g. '--sysimage=/opt/julia-env/tutorial_sysimage.so --project=/opt/julia-env')",
    )
    parser.add_argument("--python", default=sys.executable, help="Path to python3 binary for Python notebooks")
    parser.add_argument(
        "--language",
        choices=("all", "julia", "python"),
        default="all",
        help="Filter notebooks by kernel language (default: all)",
    )
    parser.add_argument(
        "--in-container-work",
        default=None,
        help="Use an existing container workspace (e.g. /home/jovyan/work) instead of copying tutorials/ into a temp dir",
    )
    parser.add_argument("--syntax-only", action="store_true", help="Only syntax-check cells without running")
    parser.add_argument("--filter", default=None, help="Only test notebooks whose relative path contains this substring")
    parser.add_argument("--timeout", type=int, default=300, help="Per-notebook timeout in seconds (default: 300)")
    args = parser.parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))

    repo_dir = Path(args.repo).resolve()
    julia_cmd = [args.julia, *shlex.split(args.julia_args)]
    python_cmd = [args.python]
    in_container_work = Path(args.in_container_work) if args.in_container_work else None

    all_notebooks = discover_notebooks(repo_dir, args.filter)
    selected: list[tuple[Path, str]] = []
    for nb_path in all_notebooks:
        nb_lang = detect_notebook_language(json.loads(nb_path.read_text(encoding="utf-8")))
        if args.language == "all" or args.language == nb_lang:
            selected.append((nb_path, nb_lang))

    if not selected:
        print("No notebooks matched!", file=sys.stderr)
        return 1

    mode = "SYNTAX-ONLY" if args.syntax_only else "FULL EXECUTION"
    print(f"=== Testing {len(selected)} interactive notebooks ({args.language}, {mode}) ===", flush=True)

    failures: list[tuple[str, str]] = []
    t_total = time.monotonic()

    for nb_path, nb_lang in selected:
        rel = str(nb_path.relative_to(repo_dir))
        print(f"\n--> {rel} [{nb_lang}]", flush=True)
        ok, dt, output = run_notebook(
            repo_dir=repo_dir,
            nb_path=nb_path,
            nb_lang=nb_lang,
            julia_cmd=julia_cmd,
            python_cmd=python_cmd,
            in_container_work=in_container_work,
            syntax_only=args.syntax_only,
            timeout_sec=args.timeout,
        )
        if ok:
            print(f"PASS {rel} ({dt:.1f}s)", flush=True)
            if output:
                for line in output.splitlines():
                    if line.strip().startswith("[OK]") or line.strip().startswith("SYNTAX OK"):
                        print(f"  {line.strip()}", flush=True)
        else:
            print(f"FAIL {rel} ({dt:.1f}s)", flush=True)
            print(output, file=sys.stderr, flush=True)
            failures.append((rel, output))

    total_dt = time.monotonic() - t_total
    print(
        f"\n=== Summary: {len(selected) - len(failures)}/{len(selected)} notebooks passed in {total_dt:.1f}s ===",
        flush=True,
    )
    if failures:
        print("Failed notebooks:", file=sys.stderr)
        for rel, _ in failures:
            print(f"  - {rel}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
