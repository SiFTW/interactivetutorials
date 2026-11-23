# Displaying the Interactive Book at `https://mitchell.science/tutorials/`

This guide connects the Jupyter Book built from `SiFTW/interactivetutorials` into your existing Netlify website (`SiFTW/MitchellLabWebsite`, served at `https://mitchell.science`) with **zero changes to your Hugo build**!

---

## Step 1: Deploy `SiFTW/interactivetutorials` on Netlify

1. Log in to [Netlify](https://app.netlify.com/) → **Add new site → Import an existing project → GitHub**.
2. Select **`SiFTW/interactivetutorials`**.
3. Netlify automatically reads [`netlify.toml`](../netlify.toml):
   - **Build command**: `npm install && npm run build:netlify`
   - **Publish directory**: `publish`
   - **Environment**: `NODE_VERSION = "22"`, `BASE_URL = "/tutorials"`
4. Click **Deploy site** and note its Netlify URL — for example, rename the site in **Site configuration → Site details** to something clean like:
   ```text
   https://mitchell-lab-tutorials.netlify.app
   ```
5. Visit `https://mitchell-lab-tutorials.netlify.app/tutorials/` to confirm the book loads cleanly.

---

## Step 2: Reverse-proxy `/tutorials/*` from `SiFTW/MitchellLabWebsite`

Add the following `[[redirects]]` rules to the bottom of **`netlify.toml`** in `https://github.com/SiFTW/MitchellLabWebsite`:

```toml
# Reverse-proxy the interactive Julia ODE Jupyter Book from SiFTW/interactivetutorials
# Replace `mitchell-lab-tutorials.netlify.app` with your actual Netlify site subdomain from Step 1.
[[redirects]]
  from = "/tutorials"
  to = "/tutorials/"
  status = 301
  force = true

[[redirects]]
  from = "/tutorials/*"
  to = "https://mitchell-lab-tutorials.netlify.app/tutorials/:splat"
  status = 200
  force = true
```

> **Why `status = 200`?** In Netlify, a `200` redirect is a **transparent reverse proxy** (rewrite): the visitor's browser stays on `https://mitchell.science/tutorials/...`, so CORS with `https://kernels.mitchell.science` sees `Origin: https://mitchell.science` and all asset paths built with `BASE_URL=/tutorials` resolve cleanly!

---

## Step 3: Add "Tutorials" to the `mitchell.science` navigation bar

In `SiFTW/MitchellLabWebsite`, edit **`config/_default/menus.yaml`** and add a `Tutorials` entry:

```yaml
  - name: Tutorials
    url: '/tutorials/'
    weight: 65
```

Commit and push both edits to `SiFTW/MitchellLabWebsite`. Once Netlify finishes deploying, visiting **`https://mitchell.science/tutorials/`** will display the full interactive Jupyter Book!
