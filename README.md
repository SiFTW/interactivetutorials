# Mitchell Lab Interactive ODE Modelling Tutorials

An interactive **Jupyter Book 2 (MyST)** teaching ordinary differential equation (ODE) modelling in **Julia** using the Mitchell Lab `CSV2Model` workflow — running live Julia kernels in the browser backed by isolated, disposable Docker containers on our lab server (`139.184.169.98`), and published seamlessly at `https://mitchell.science/tutorials/`.

## Architecture

```
Browser at https://mitchell.science/tutorials/
   │
   ├── Static Jupyter Book 2 HTML/JS (Netlify reverse proxy → this repo)
   │
   └── Live Code (Thebe / BinderHub SSE + WebSockets)
         │  HTTPS / WSS
         ▼
   Cloudflare Tunnel (https://kernels.mitchell.science)
         │
         ▼
   server/spawner (127.0.0.1:8787 on 139.184.169.98)
         │  Isolated Docker network (internal: true — NO internet/LAN egress)
         ▼
   Per-user ephemeral Docker containers (mitchell-lab/julia-tutorial-kernel)
   • Pre-installed & precompiled DifferentialEquations.jl, Plots.jl, CSV.jl, DataFrames.jl
   • Fresh copy of tutorials/toyModel/* per reader
   • Hard CPU/RAM/PID caps + automatic 20-min idle culling
   • Zero changes to existing production JupyterHub (jeanlucpacard.mitchell.science)
```

## Repository Structure

| Path | Purpose |
|---|---|
| [`myst.yml`](./myst.yml) | Jupyter Book 2 (MyST) configuration with live execution pointing to `https://kernels.mitchell.science` |
| [`netlify.toml`](./netlify.toml) | Netlify build config producing the static site under `publish/tutorials/` (`BASE_URL=/tutorials`) |
| [`book/`](./book/) | Tutorial landing page, SVG reaction diagrams, and interactive Julia notebooks (`tutorial-1/`) |
| [`tutorials/toyModel/`](./tutorials/toyModel/) | Canonical `csv2model-multiscale.py` and starter CSV files baked into every user's Julia container |
| [`server/`](./server/) | Self-contained Docker Compose stack: precompiled Julia kernel image + lightweight Binder-API spawner & proxy |
| [`server/DEPLOYMENT.md`](./server/DEPLOYMENT.md) | Zero-downtime deployment runbook for `139.184.169.98` + Cloudflare Tunnel |
| [`netlify-integration/mitchell-lab-website-patch.md`](./netlify-integration/mitchell-lab-website-patch.md) | Exact `netlify.toml` proxy rule and menu entry for `SiFTW/MitchellLabWebsite` |

## Local Preview (Book Frontend)

Requires Node.js 20+:

```bash
npm install
npm start
```

Open `http://localhost:3000` in your browser. To build the exact static output Netlify deploys:

```bash
npm run build:netlify
```

## Running Spawner Tests Locally

```bash
pip install -r server/spawner/requirements.txt pytest pytest-asyncio
pytest -v server/spawner/tests/test_spawner.py
```

## Deployment Checklist

1. **Deploy the isolated Julia kernel backend on `139.184.169.98`** → follow [`server/DEPLOYMENT.md`](./server/DEPLOYMENT.md).
2. **Deploy this repo on Netlify & proxy `/tutorials/*` from `mitchell.science`** → follow [`netlify-integration/mitchell-lab-website-patch.md`](./netlify-integration/mitchell-lab-website-patch.md).
