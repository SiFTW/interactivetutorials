# Modelling Across Scales: From Molecules to Pandemics

Welcome to the **Brighton and Sussex Medical School (BSMS) Student Selected Component (SSC)** taught by the [Mitchell Lab](https://mitchell.science/).

This interactive book combines our **in-class lecture slides** and **live Julia computational simulations** in one place—no logins, software installation, or prior coding or mathematics background required.

:::{tip} Two Ways to Use This Book
- **📖 Reading Mode (default):** Scroll through the explanations, diagrams, equations, and pre-computed plots at your own pace, and click **⚡ Activate Live Editable Julia Cells** whenever you want to edit parameters and run simulations in your browser.
- **📽️ Present Slides:** Click **📽️ Present Slides** (top toolbar or top-right header) to step section-by-section in full-screen slide view—ideal for presenting in class while running live Julia simulations right on the projector. Press `Esc` or click **📖 Reading Mode** at any time to return.
:::

---

## SSC Structure (8 Weeks)

Across this SSC, we explore how computational simulations help us understand biology and medicine across three very different scales—from individual protein atoms up to entire human populations:

![Modelling across biological scales](images/scales-overview.svg)

| Week | Topic | Scale | Status |
| :--- | :--- | :--- | :--- |
| **Week 1** | **Intro to Computational Modelling & Population-Scale Models (SI, SIS, SIR, SIRS, SEIR)** | Populations & Public Health | **Live in this book** |
| **Week 2** | Molecular Dynamics Modelling 1 | Atoms & Proteins | *Slides on [mitchell.science/post/teaching](https://mitchell.science/post/teaching/)* |
| **Week 3** | Molecular Dynamics Modelling 2 | Atoms & Proteins | *Slides on [mitchell.science/post/teaching](https://mitchell.science/post/teaching/)* |
| **Week 4** | **Cell Signalling Modelling: NF-κB in Blood Cancer (CLL & Waldenström)** | Cells & Biochemical Networks | **Live in this book** |
| **Week 5** | **Cell Fate Modelling: Apoptosis (BCL2) & Cell Cycle (c-MYC)** | Cells & Biochemical Networks | **Live in this book** |
| **Week 6** | Preparation for Assessment (no taught session) | — | Independent project work |
| **Week 7** | Assessment Week 1 (6-minute presentations — all attend) | — | Presentation |
| **Week 8** | Assessment Week 2 (6-minute presentations — all attend) | — | Presentation |

---

## Start Exploring

### Week 1 — Introduction & Population-Scale Modelling
- [**1.1 Introduction to Computational Modelling**](week-1/01-intro-to-modelling.md) — Overview, learning outcomes, and real-world outbreak ODEs
- [**1.2 The SI & SIS Model**](week-1/02-si-sis-model.ipynb) — Your first two-compartment outbreak model
- [**1.3 The SIR & SIRS Model**](week-1/03-sir-sirs-model.ipynb) — Adding immunity and waning immunity
- [**1.4 Endemic SIR: Births & Deaths**](week-1/04-endemic-sir-model.ipynb) — Population turnover and recurrent waves
- [**1.5 The SEIR Model & Wrap-Up**](week-1/05-seir-model.ipynb) — Incubation periods, disease-induced mortality, and discussion

### Cell Signalling Modelling — NF-κB in Blood Cancer
- [**2.1 NF-κB Signalling in Blood Cancer & Systems Biology**](signalling/01-nfkb-and-systems-biology.md) — WM, CLL, DLBCL, canonical vs non-canonical NF-κB, and the systems biology loop
- [**2.2 Guided Practical: Simulating CLL & Drug Responses**](signalling/02-cll-tri-model-simulation.ipynb) — Build the 140-species NF-κB Tri-Model and compare M-CLL, U-CLL, and IKK inhibition
- [**2.3 Drug Discovery for Waldenström Macroglobulinemia**](signalling/03-waldenstrom-drug-discovery.ipynb) — Switch on MYD88 L265P and screen targeted drugs & combinations

### Cell Fate Modelling — Apoptosis & Cell Cycle (*Norris et al., 2024*)
- [**3.1 Cell Fate Modelling: Apoptosis & the Cell Cycle**](cell-fate/01-apoptosis-and-cell-cycle-intro.md) — Double-Hit Lymphoma, BCL2, c-MYC, and the Apoptosis & Cell Cycle networks
- [**3.2 Apoptosis Modelling: BCL2 Delays Cell Death (Figure 1B)**](cell-fate/02-apoptosis-bcl2-model.ipynb) — Simulate the 59-species Apoptosis model, sweep BCL2 (1×–100×), and screen rescue genes
- [**3.3 Cell Cycle Modelling: c-MYC Shortens G1 (Figure 1E)**](cell-fate/03-cell-cycle-myc-model.ipynb) — Simulate the 37-species Cell Cycle model, prove G1 shortens with c-MYC, and rescue G1 shortening
