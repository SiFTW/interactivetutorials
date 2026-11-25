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

:::{note} Want to follow along on your own machine or the lab JupyterHub?
Every notebook page can also be downloaded as a `.ipynb` file (or opened from the [GitHub repository](https://github.com/SiFTW/interactivetutorials)). When you transition from these tutorials to full-scale lab research, see the [Mitchell Lab Handbook](https://docs.mitchell.science/) for connecting to our research compute servers.
:::
