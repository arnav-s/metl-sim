# README — Rosetta FastRelax Shell Sweep (Repack & Minimization Distance Study)

This project automates a systematic exploration of FastRelax in Rosetta by sweeping two key parameters:

- Repack shell distance (relax_repack_distance)
- Minimization shell distance (relax_minimize_distance)

A total of 14 Rosetta runs are generated and executed. Each run produces:

- A unique XML script
- A unique flags file
- A unique .sc scorefile
- A unique .log file (runtime parsed later)
- A unique output prefix

After all runs complete, a second script parses the results into a dataframe and generates six publication-quality plots.

---------------------------------------------------------------------

## 1. Required Input Files

Your working directory must contain:

relax_temp.xml
flags_relax_temp
prepare_pab1_raw_0001.pdb
make_relax_sweep.py
parse_and_plot.py

---------------------------------------------------------------------

## 2. Parameter Sweeps Performed

### Sweep A — Repack Shell Distance
Minimization shell distance fixed at 10000.

Repack distances tested:
0
3
6
9
12
15

### Sweep B — Minimization Shell Distance
Repack shell distance fixed at 10000.

Minimization distances tested:
5
10
15
20
25
30
35
40

Total runs: 14

---------------------------------------------------------------------

## 3. Generate XML & Flags Files

Run:

python make_relax_sweep.py

This script generates:

- relax_rX_mY.xml — XML file with substituted distances
- flags_rX_mY — flags file containing:
  • correct -parser:protocol link
  • unique scorefile name (relax_rX_mY.sc)
  • unique output prefix (flags_rX_mY_)
  • unique log filename (flags_rX_mY.log)
  • correct input PDB: -s prepare_pab1_raw_0001.pdb
- run_all_relax.sh — batch script to run all 14 jobs

---------------------------------------------------------------------

## 4. Execute All Rosetta Jobs

Make executable:

chmod +x run_all_relax.sh

Run:

./run_all_relax.sh

Each job produces:

relax_rX_mY.sc   (scorefile)
flags_rX_mY.log  (logfile with runtime information)

---------------------------------------------------------------------

## 5. Parse Outputs & Generate Plots

After all runs finish:

python parse_and_plot.py

The parser extracts:

From .sc files:
- total_score

From .log files:
- runtime (seconds), parsed from:
  protocols.jd2.JobDistributor: 1 jobs considered, 1 jobs attempted in XX seconds

The script builds a dataframe with:

repack_distance
minimize_distance
total_score
runtime
filename

Saved as:

results.csv

The script produces six plots (stored in plots/):

1. Total score vs repack distance
2. Total score vs minimization distance
3. Runtime vs repack distance
4. Runtime vs minimization distance
5. Runtime vs total score (repack sweep)
6. Runtime vs total score (minimization sweep)

Plot formatting:
- Title: "Pab1 L55A\nCartesian optimization"
- Font: Times New Roman, size 18
- Clear marker styling

---------------------------------------------------------------------

## 6. Workflow Output Summary

After running the entire workflow, your directory will contain:

14 XML files
14 flags files
14 .sc scorefiles
14 .log files
results.csv (aggregate dataframe)
plots/ (all generated figures)
run_all_relax.sh (batch run script)

This workflow provides a reproducible analysis of how local repacking radius and minimization radius affect Rosetta FastRelax performance.
