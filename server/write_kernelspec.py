"""Write a deterministic Jupyter kernelspec named 'julia' for the tutorial image."""

import json
import os

KERNEL_JSON_PATH = "/usr/local/share/jupyter/kernels/julia/kernel.json"
SYSIMAGE_PATH = "/opt/julia-env/tutorial_sysimage.so"


def main() -> None:
    argv = ["julia", "--project=/opt/julia-env", "-i", "--color=yes"]
    if os.path.isfile(SYSIMAGE_PATH):
        argv.append(f"--sysimage={SYSIMAGE_PATH}")
    # Modern IJulia (>=1.29) launches via `import IJulia; IJulia.run_kernel()`
    # rather than executing src/kernel.jl directly.
    argv.extend(["-e", "import IJulia; IJulia.run_kernel()", "{connection_file}"])

    spec = {
        "display_name": "Julia",
        "language": "julia",
        "interrupt_mode": "signal",
        "argv": argv,
        "env": {
            "GKSwstype": "100",
            "JULIA_NUM_THREADS": "2",
            "JULIA_DEPOT_PATH": "/opt/julia",
            "JULIA_PROJECT": "/opt/julia-env",
        },
    }

    os.makedirs(os.path.dirname(KERNEL_JSON_PATH), exist_ok=True)
    with open(KERNEL_JSON_PATH, "w", encoding="utf-8") as fp:
        json.dump(spec, fp, indent=2)
    print(f"Wrote kernelspec to {KERNEL_JSON_PATH}:")
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
