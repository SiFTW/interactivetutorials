#!/usr/bin/env python3
"""End-to-end Julia notebook execution test suite for Mitchell Lab interactive books.

Executes every code cell of every `.ipynb` notebook in `book/` and `ssc/` sequentially
in an isolated Julia process (matching how a student runs all cells in order via Thebe
or JupyterLab), verifying:
  1. Zero banned non-sysimage heavy package imports (prevents 2 GB container OOM crashes).
  2. Every code cell parses cleanly with Julia's `Meta.parseall`.
  3. Every code cell executes with zero uncaught exceptions in `Main` top-level scope.
  4. Every `Plots.Plot` returned or passed to `display(...)` renders cleanly to SVG
     under headless GR (`GKSwstype=100`).

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

    for sub in ("NFkB", "apoptosis", "cellCycle"):
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
    julia_cmd: list[str],
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

    banned = check_banned_imports(rel, code_cells)
    if banned:
        return False, 0.0, "\n".join(banned)

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nbtest_") as td:
        td_path = Path(td)
        runner_path = td_path / "runner.jl"
        runner_path.write_text(JULIA_RUNNER, encoding="utf-8")

        cell_paths: list[str] = []
        for idx, src in enumerate(code_cells, 1):
            cp = td_path / f"cell_{idx:02d}.jl"
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

        cmd = [
            *julia_cmd,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute all interactive Julia notebooks and fail on any cell error.")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent), help="Path to repo root")
    parser.add_argument("--julia", default="julia", help="Path to julia binary")
    parser.add_argument(
        "--julia-args",
        default="",
        help="Extra flags passed to julia (e.g. '--sysimage=/opt/julia-env/tutorial_sysimage.so --project=/opt/julia-env')",
    )
    parser.add_argument(
        "--in-container-work",
        default=None,
        help="Use an existing container workspace (e.g. /home/jovyan/work) instead of copying tutorials/ into a temp dir",
    )
    parser.add_argument("--syntax-only", action="store_true", help="Only parse cells with Meta.parseall without running")
    parser.add_argument("--filter", default=None, help="Only test notebooks whose relative path contains this substring")
    parser.add_argument("--timeout", type=int, default=300, help="Per-notebook timeout in seconds (default: 300)")
    args = parser.parse_args()

    repo_dir = Path(args.repo).resolve()
    julia_cmd = [args.julia, *shlex.split(args.julia_args)]
    in_container_work = Path(args.in_container_work) if args.in_container_work else None

    notebooks = discover_notebooks(repo_dir, args.filter)
    if not notebooks:
        print("No notebooks matched!", file=sys.stderr)
        return 1

    mode = "SYNTAX-ONLY" if args.syntax_only else "FULL EXECUTION"
    print(f"=== Testing {len(notebooks)} interactive Julia notebooks ({mode}) ===", flush=True)

    failures: list[tuple[str, str]] = []
    t_total = time.monotonic()

    for nb_path in notebooks:
        rel = str(nb_path.relative_to(repo_dir))
        print(f"\n--> {rel}", flush=True)
        ok, dt, output = run_notebook(
            repo_dir=repo_dir,
            nb_path=nb_path,
            julia_cmd=julia_cmd,
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
        f"\n=== Summary: {len(notebooks) - len(failures)}/{len(notebooks)} notebooks passed in {total_dt:.1f}s ===",
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
