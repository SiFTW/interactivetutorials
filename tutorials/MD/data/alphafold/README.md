# Bundled AlphaFold DB, Experimental PDB & MYD88 MD Teaching Dataset

All files in this directory are pre-bundled for offline (`--network=none`) execution inside the Mitchell Lab teaching containers.

## Sources & Licences

| File(s) | Protein / Content | Source & Licence |
| :--- | :--- | :--- |
| `AF-Q99836-F1-model_v6.pdb`, `AF-Q99836-F1-pae_v6.json`, `AF-Q99836-F1-am.csv` | Human **MYD88** (UniProt `Q99836`, 296 aa): AlphaFold DB v6 structure, PAE matrix & AlphaMissense substitution table | EMBL-EBI AlphaFold DB / Google DeepMind (CC-BY-4.0); Jumper et al., *Nature* (2021); Cheng et al., *Science* (2023) |
| `AF-P68871-F1-model_v6.pdb`, `AF-P68871-F1-am.csv` | Human **Haemoglobin subunit β** (`P68871`, 147 aa — Sickle-Cell `E6V` / `E7V`) | EMBL-EBI AlphaFold DB / Google DeepMind (CC-BY-4.0) |
| `AF-P01308-F1-model_v6.pdb`, `AF-P01308-F1-pae_v6.json`, `AF-P01308-F1-am.csv` | Human **Proinsulin** (`P01308`, 110 aa — Akita neonatal diabetes `C96Y`) | EMBL-EBI AlphaFold DB / Google DeepMind (CC-BY-4.0) |
| `myd88_tir_4EO7_xray.pdb` | Experimental monomeric X-ray structure of human MYD88 TIR domain (Chain A, res 157–296) | RCSB PDB `4EO7` (Snyder et al., 2013) |
| `myd88_tir_7L6W_assembly.pdb` | Experimental SFX structure of human MYD88 TIR higher-order assembly (Chain A, res 157–296) | RCSB PDB `7L6W` (Clabbers et al., *Nat. Commun.*, 2021) |
| `myd88_tir_AF_wt.pdb`, `myd88_tir_AF_L252P.pdb` | Excised MYD88 TIR domain (res 157–296) from `AF-Q99836-F1` and its *in-silico* `L252P` (clinical `L265P`) mutant | Derived from `AF-Q99836-F1-model_v6.pdb` |
| `myd88_tir_wt_md.pdb`, `myd88_tir_wt_50ps.dcd`, `myd88_tir_L252P_md.pdb`, `myd88_tir_L252P_50ps.dcd` | Pre-computed 50 ps OpenMM MD trajectories (`amber10.xml`, `300 K`, 2 fs timestep, heavy atoms saved every 1 ps, 50 frames) with AlphaFold pLDDT preserved in the PDB B-factor column | Generated with OpenMM 8 (`LangevinMiddleIntegrator`, `CutoffNonPeriodic`, `1.0 nm`, `HBonds`) |
