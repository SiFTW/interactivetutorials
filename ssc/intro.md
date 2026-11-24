# Modelling Across Scales: From Molecules to Pandemics

Welcome to the **Brighton and Sussex Medical School (BSMS) Student Selected Component (SSC)** taught by the [Mitchell Lab](https://mitchell.science/).

This interactive book combines our **in-class lecture slides** and **live Julia & Python computational simulations** in one place—no logins, software installation, or prior coding or mathematics background required.

:::{tip} Two Ways to Use This Book
- **📖 Reading Mode (default):** Scroll through the explanations, diagrams, equations, 3D protein viewers, and pre-computed plots at your own pace, and click **⚡ Activate Live Editable Cells** whenever you want to edit parameters and run live simulations in your browser.
- **📽️ Present Slides:** Click **📽️ Present Slides** (top toolbar or top-right header) to step section-by-section in full-screen slide view—ideal for presenting in class while running live simulations right on the projector. Press `Esc` or click **📖 Reading Mode** at any time to return.
:::

---

## SSC Structure (8 Weeks)

Across this SSC, we explore how computational simulations help us understand biology and medicine across three very different scales—from individual protein atoms up to entire human populations:

![Modelling across biological scales](images/scales-overview.svg)

| Week | Topic | Scale | Language | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Week 1** | **Intro to Computational Modelling & Population-Scale Models (SI, SIS, SIR, SIRS, SEIR)** | Populations & Public Health | Julia | **Live in this book** |
| **Week 2** | **Molecular Dynamics I: Force Fields, Equations & Protein Structures (`.pdb`)** | Atoms & Proteins | Python | **Live in this book** |
| **Week 3** | **Molecular Dynamics II: Energy Landscapes, OpenMM Protein Folding & Analysis** | Atoms & Proteins | Python | **Live in this book** |
| **Week 4** | **Cell Signalling Modelling: NF-κB in Blood Cancer (CLL & Waldenström)** | Cells & Biochemical Networks | Julia | **Live in this book** |
| **Week 5** | **Cell Fate Modelling: Apoptosis (BCL2) & Cell Cycle (c-MYC)** | Cells & Biochemical Networks | Julia | **Live in this book** |
| **Week 6** | Preparation for Assessment (no taught session) | — | — | Independent project work |
| **Week 7** | Assessment Week 1 (6-minute presentations — all attend) | — | — | Presentation |
| **Week 8** | Assessment Week 2 (6-minute presentations — all attend) | — | — | Presentation |

---

## Start Exploring

### Week 1 — Introduction & Population-Scale Modelling *(Julia)*
- [**1.1 Introduction to Computational Modelling**](week-1/01-intro-to-modelling.md) — Overview, learning outcomes, and real-world outbreak ODEs
- [**1.2 The SI & SIS Model**](week-1/02-si-sis-model.ipynb) — Your first two-compartment outbreak model
- [**1.3 The SIR & SIRS Model**](week-1/03-sir-sirs-model.ipynb) — Adding immunity and waning immunity
- [**1.4 Endemic SIR: Births & Deaths**](week-1/04-endemic-sir-model.ipynb) — Population turnover and recurrent waves
- [**1.5 The SEIR Model & Wrap-Up**](week-1/05-seir-model.ipynb) — Incubation periods, disease-induced mortality, and discussion

### Week 2 — Molecular Dynamics I: Force Fields & Protein Structures *(Python)*
- [**2.1 Molecular Dynamics I: Force Fields, Equations & PDB Files**](molecular-dynamics/01-md-intro-and-force-fields.md) — Protein structure, bonded & non-bonded force fields, Newton's equations, ensembles, PBCs, and the RCSB PDB activity
- [**2.2 Guided Activity: Exploring PDB Structures in Python**](molecular-dynamics/02-exploring-pdb-structures.ipynb) — Parse `.pdb` coordinates, rotate 3D protein models (`villin_water.pdb`, `polyALA.pdb`, `polyGLY.pdb`), and build a custom 3D peptide spelling your own name

### Week 3 — Molecular Dynamics II: Simulating & Analysing Protein Folding *(Python)*
- [**3.1 Molecular Dynamics II: Energy Landscapes & Trajectory Analysis**](molecular-dynamics/03-energy-landscapes-and-analysis.md) — Energy barriers, the sampling problem, secondary structure (DSSP), H-bonds, Ramachandran plots, and RMSD
- [**3.2 Live OpenMM Practical: Simulating Protein Folding**](molecular-dynamics/04-protein-folding-simulation.ipynb) — Simulate 200 ps of `polyALA.pdb` folding into an $\alpha$-helix at $300\text{ K}$, watch the animated 3D trajectory, plot end-to-end distance & Ramachandran transitions, and test temperature, polyglycine, or your own name peptide

### Week 4 — Cell Signalling Modelling: NF-κB in Blood Cancer *(Julia)*
- [**4.1 NF-κB Signalling in Blood Cancer & Systems Biology**](signalling/01-nfkb-and-systems-biology.md) — WM, CLL, DLBCL, canonical vs non-canonical NF-κB, and the systems biology loop
- [**4.2 Guided Practical: Simulating CLL & Drug Responses**](signalling/02-cll-tri-model-simulation.ipynb) — Build the 140-species NF-κB Tri-Model and compare M-CLL, U-CLL, and IKK inhibition
- [**4.3 Drug Discovery for Waldenström Macroglobulinemia**](signalling/03-waldenstrom-drug-discovery.ipynb) — Switch on MYD88 L265P and screen targeted drugs & combinations

### Week 5 — Cell Fate Modelling: Apoptosis & Cell Cycle *(Norris et al., 2024 — Julia)*
- [**5.1 Apoptosis, Cell Cycle & Double-Hit Lymphoma**](cell-fate/01-apoptosis-and-cell-cycle-intro.md) — Double-Hit Lymphoma, BCL2, c-MYC, and the Apoptosis & Cell Cycle networks
- [**5.2 Apoptosis Modelling: BCL2 Delays Cell Death (Figure 1B)**](cell-fate/02-apoptosis-bcl2-model.ipynb) — Simulate the 59-species Apoptosis model, sweep BCL2 (1×–100×), and screen rescue genes
- [**5.3 Cell Cycle Modelling: c-MYC Shortens G1 (Figure 1E)**](cell-fate/03-cell-cycle-myc-model.ipynb) — Simulate the 37-species Cell Cycle model, prove G1 shortens with c-MYC, and rescue G1 shortening
