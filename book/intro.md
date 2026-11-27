# Interactive ODE Modelling in Julia

Welcome to the **Mitchell Lab Interactive Modelling Tutorials**!

This interactive Jupyter Book teaches you how to build, simulate, and modify ordinary differential equation (ODE) models of biomolecular networks in **Julia** using the Mitchell Lab `CSV2Model` workflow — **directly in your web browser, with nothing to install and no server login required**.

## How to run the live Julia code

Every tutorial page in this book contains real, editable Julia code cells backed by an isolated Julia kernel running on our lab compute server.

:::{tip} Launching your live editable Julia session
1. Open any tutorial chapter from the sidebar on the left.
2. Click the **Activate Live Editable Julia Cells** button near the top of the page to launch your own private, sandboxed Julia kernel (it takes just a few seconds because `DifferentialEquations.jl`, `Plots.jl`, and `CSV2Model` are already pre-installed and precompiled!).
3. Once connected, every code block turns into an **editable code editor** — click inside any cell to modify the code and press **Shift + Enter** (or click the **Run** button underneath the cell) to re-run the simulation and watch the plots update live.
:::

Each reader gets a **fresh, isolated workspace** containing all the starter model files (`reactions.csv`, `parameters.csv`, `ratelaws.csv`, and `csv2model-multiscale.py`), so you can freely modify parameters, edit CSV definitions, and experiment without affecting anyone else. Sessions automatically reset after 20 minutes of inactivity.

## What you will learn in Tutorial 1

1. **[Running the Toy Model](./tutorial-1/01-running-the-toy-model.ipynb)** — Meet the 3-protein biochemical cascade ($\emptyset \to A \to B \to C \to \emptyset$), run your first Julia ODE simulation, understand every line of code, and solve hands-on challenges on initial conditions, simulation time, and plot resolution.
2. **[How Models Are Made](./tutorial-1/02-how-models-are-made.ipynb)** — Discover how biological reaction diagrams translate into systems of ODEs, and explore the three CSV tables (`reactions.csv`, `parameters.csv`, `ratelaws.csv`) that `CSV2Model` combines into runnable Julia code.
3. **[Editing & Extending Models](./tutorial-1/03-editing-models-challenges.ipynb)** — Modify expression and degradation rates live, inspect how the generated ODEs change, and extend the pathway by adding a brand-new biomolecular species **D** ($\emptyset \to A \to B \to C \to D \to \emptyset$).

## What you will learn in Tutorial 2

1. **[Modifiers & Induced Expression](./tutorial-2/01-modifiers-and-induction.ipynb)** — Learn how **modifiers** (like transcription factors or enzymes) control reaction rates without being consumed, build an **NF-κB → IκB** induced expression model, and practice reading Julia error messages.
2. **[Modifier Challenges (NF-κB / IκB Pathway)](./tutorial-2/02-modifier-challenges.ipynb)** — Stabilise `IkB` with basal expression and degradation, add reversible **`NFkB` + `IkB` binding/unbinding**, and expand the pathway with **`IkB` mRNA** transcription and translation.

## What you will learn in Tutorial 3

1. **[CSV2Julia Rules, Parameter Naming & Modes](./tutorial-3/01-csv2julia-rules-and-modes.ipynb)** — Learn the rules of `CSV2Julia` (species placeholders, the `prefix_label` underscore naming convention, and parameter numbering), compare **`inline`**, **`scan`**, and **`param`** modes side by side, and modify parameters at run-time on the Toy Model without regenerating ODE code.
2. **[Creating Time-Dependent Input Curves](./tutorial-3/02-time-dependent-inputs.ipynb)** — Learn how time-dependent functions $f(t)$ work, build constant, pulse, smooth-decay, and linearly interpolated experimental input curves, and swap dynamic inputs into the Toy Model at run-time using `CSV2Julia`'s `(t)` syntax.
3. **[Running the Published NF-κB Model](./tutorial-3/03-published-nfkb-model.ipynb)** — Generate and simulate the published **101-species, 257-parameter NF-κB model** ([`SiFTW/NFkBModel`](https://github.com/SiFTW/NFkBModel)), apply canonical **NEMO/IKK** and non-canonical **NIK** inputs to observe nuclear **RelA:p50** (`RelAnp50n`) and **RelB:p52** (`RelBnp52n`) increasing respectively, and test runtime parameter perturbations.

## What you will learn in Tutorial 4

1. **[Combining Modules into the BCR–TLR–NF-κB Tri-Model](./tutorial-4/01-combining-modules.ipynb)** — Learn how `combineModels` merges separate `BCR`, `TLR`, `NFkB`, and `linking` CSV modules into a single 150-species, 444-parameter model, why conserved upstream pools need non-zero initial conditions, and how BCR and TLR signals drive nuclear `RelAnp50n`.
2. **[Recreating Figure 5 of Jayawant *et al.*](./tutorial-4/02-recreating-figure-5.ipynb)** — Simulate heterogeneous virtual populations of four DLBCL cell lines (`RIVA`, `U2932 R1`, `U2932 R2`, and `HBL1`) with their genetic mutations (`TAK1`, `CD79B`, `MYD88`), reproduce the steady-state and TLR9 fold-change plots from Figure 5 of Jayawant *et al.*, and dissect the contribution of each mutation.
3. **[Microenvironment & NF-κB Crosstalk Across Cell Lines (Vareli *et al.* Figure 6A–B)](./tutorial-4/03-microenvironment-crosstalk-figure6.ipynb)** — Add the downstream `BCL2` module (`BCL2`, `BCL-xL`, `MCL1`), simulate CD40L tumour-microenvironment signalling in `RIVA` (low basal BCR) vs `SUDHL8` (high basal BCR/BTK), and recreate **Figure 6A** (IκBα/IκBε → IκBδ sequestration shift) and **Figure 6B** (24-hour nuclear `RelA:p50`, `RelB:p52`, and `cRel:p50` crosstalk).
4. **[BH3-Mimetic Resistance, BTK/NIK Rescue & IκB Knockouts (Vareli *et al.* Figures 6–7)](./tutorial-4/04-btk-rescue-and-ikb-knockouts.ipynb)** — Connect `RelB` and `cRel` crosstalk to anti-apoptotic `BCL-xL` and `MCL1` induction, compare **BTK inhibition** (ibrutinib) against **NIK inhibition** (Amgen16) for overcoming microenvironment-driven resistance, and recreate the `IκBε` knockout vs `IκBα` mutant validation simulations.

## What you will learn in Tutorial 5

1. **[Apoptosis Timing & Scanning BCL2 (Norris *et al.* Figure 1B)](./tutorial-5/01-apoptosis-bcl2-figure1b.ipynb)** — Build the 59-species apoptosis ODE model, clamp the external death-ligand species with `fixSpecies.jl`, scan **BCL2** overexpression (`1×` to `100×`) to measure time to cell death (`Cleaved PARP > 10%`), and explore the clinical relevance of `BCL2` deregulation and BH3 mimetics (venetoclax).
2. **[Cell Cycle Timing & Scanning c-MYC (Norris *et al.* Figure 1E)](./tutorial-5/02-cell-cycle-myc-figure1e.ipynb)** — Build the 37-species cell-cycle ODE model with mitotic division callbacks (`ContinuousCallback`), scan **c-MYC** overexpression (`1×` to `100×`) to see why **G1** specifically shortens, and connect `BCL2` + `MYC` Double-Hit Lymphoma to upcoming multiscale modelling.

## What you will learn in Tutorial 6

1. **[From Separate Modules to One Dividing, Dying Cell](./tutorial-6/01-building-a-dividing-dying-cell.ipynb)** — Combine the `NFkB`, `cellCycle`, `apoptosis`, `differentiation`, and `linking` modules into the **193-species, 563-parameter** multiscale B-cell model, learn how `ContinuousCallback` tripwires trigger mitotic division and apoptosis, and trace a single virtual cell's branching lineage tree.
2. **[Heterogeneous Populations & MYC + BCL2 Synergy (Norris *et al.* Figure 2B)](./tutorial-6/02-double-hit-myc-bcl2-figure2.ipynb)** — Scale up to heterogeneous virtual B-cell populations (`preCV = 0.11`), quantify **super-additive synergy** vs additivity in **MYC + BCL2** Double-Hit Lymphoma, and test simulated venetoclax / CDK4/6 interventions.
3. **[Why MYC + BCL6 Differs from MYC + BCL2 (Norris *et al.* Figure 2C)](./tutorial-6/03-double-hit-myc-bcl6-vs-bcl2.ipynb)** — Compare **MYC + BCL6** against **MYC + BCL2**, inspect the `BCL6 ⊣ Blimp1` differentiation circuit to see why WHO 2022 reclassified *MYC*+*BCL6*, and test general **AA + PP** synergy (such as multiple myeloma `gain1q`).

## What you will learn in Tutorial 7

1. **[Patient Virtual Avatars & 6-Hour Biomarkers (Norris *et al.* Figure 3)](./tutorial-7/01-patient-avatars-and-6h-biomarkers.ipynb)** — Map real DLBCL sequencing data (`patientData.csv` and `muts2ParamsNEW.csv`) directly into individual virtual B-cell avatars, see how upstream NF-κB mutations mimic both MYC and BCL2, stratify 12 real patients by 6-hour `Cdh1`, `cSmac`, and `cCytoC`, and test personalised targeted drugs.
2. **[From 6-Hour Simulations to 10-Year Clinical Survival (Norris *et al.* Figures 4 & 5)](./tutorial-7/02-predicting-clinical-survival-figures4-5.ipynb)** — Build Kaplan–Meier survival curves and log-rank tests from first principles in Julia across **466 real DLBCL patients** (Discovery Cohort C1 and Validation Cohort C2), and combine `AAPP` signalling with genetic clusters and clinical IPI to stratify long-term prognosis.

:::{note} Want to follow along on your own machine or the lab JupyterHub?
Every notebook page can also be downloaded as a `.ipynb` file (or opened from the [GitHub repository](https://github.com/SiFTW/interactivetutorials)). When you transition from these tutorials to full-scale lab research, see the [Mitchell Lab Handbook](https://docs.mitchell.science/) for connecting to our research compute servers.
:::
