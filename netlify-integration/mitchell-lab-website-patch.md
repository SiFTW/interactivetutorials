# Displaying the Interactive Books at `https://mitchell.science/tutorials/` and `https://mitchell.science/ssc/`

This guide connects both Jupyter Books built from `SiFTW/interactivetutorials` into your existing Netlify website (`SiFTW/MitchellLabWebsite`, served at `https://mitchell.science`) with **zero changes to your Hugo build**!

- **`book/` → `publish/tutorials/`** → served at **`https://mitchell.science/tutorials/`** (ODE Modelling Tutorials)
- **`ssc/` → `publish/ssc/`** → served at **`https://mitchell.science/ssc/`** (BSMS SSC: Modelling Across Scales)

---

## Step 1: Deploy `SiFTW/interactivetutorials` on Netlify

1. Log in to [Netlify](https://app.netlify.com/) → **Add new site → Import an existing project → GitHub** (already done if `mitchell-lab-tutorials.netlify.app` is live).
2. Netlify automatically reads [`netlify.toml`](../netlify.toml) and builds **both** `publish/tutorials/` and `publish/ssc/`.
3. Verify both direct Netlify paths load cleanly:
   - `https://mitchell-lab-tutorials.netlify.app/tutorials/`
   - `https://mitchell-lab-tutorials.netlify.app/ssc/`

---

## Step 2: Reverse-proxy `/tutorials/*` and `/ssc/*` from `SiFTW/MitchellLabWebsite`

In `https://github.com/SiFTW/MitchellLabWebsite`, add/keep these `[[redirects]]` rules at the bottom of **`netlify.toml`** (replacing `mitchell-lab-tutorials.netlify.app` with your actual Netlify site subdomain):

```toml
# Reverse-proxy the interactive Julia ODE Tutorials (/tutorials)
[[redirects]]
  from = "/tutorials"
  to = "https://mitchell-lab-tutorials.netlify.app/tutorials/"
  status = 200
  force = true

[[redirects]]
  from = "/tutorials/*"
  to = "https://mitchell-lab-tutorials.netlify.app/tutorials/:splat"
  status = 200
  force = true

# Reverse-proxy the BSMS SSC Interactive Book (/ssc)
[[redirects]]
  from = "/ssc"
  to = "https://mitchell-lab-tutorials.netlify.app/ssc/"
  status = 200
  force = true

[[redirects]]
  from = "/ssc/*"
  to = "https://mitchell-lab-tutorials.netlify.app/ssc/:splat"
  status = 200
  force = true
```

> **Important:** Do **not** add a `301` redirect from `/ssc` to `/ssc/` (or `/tutorials` to `/tutorials/`) — Netlify's Pretty URLs treats both as the same path, so a `301` between them causes an infinite redirect loop! Using `status = 200` on both rules transparently proxies the page with zero redirects.

---

## Step 3: Optional — Add Navigation Links on `mitchell.science`

In `SiFTW/MitchellLabWebsite`, you can add links in **`config/_default/menus.yaml`** (or link directly from `/post/teaching/`):

```yaml
  - name: Tutorials
    url: '/tutorials/'
    weight: 65
  - name: SSC
    url: '/ssc/'
    weight: 66
```

Once committed and deployed on Netlify, visiting **`https://mitchell.science/ssc/`** will load the full interactive BSMS SSC book (with **📽️ Present Slides** mode for class and live Julia simulations)!
