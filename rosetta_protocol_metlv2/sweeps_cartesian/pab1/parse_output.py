#!/usr/bin/env python3
import glob
import re
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def parse_r_m_from_filename(filename: str):
    """
    Expect filenames like: relax_r10000_m35.sc
    Returns (r, m) as ints.
    """
    base = Path(filename).name  # relax_r10000_m35.sc
    match = re.match(r"relax_r(\d+)_m(\d+)\.sc$", base)
    if not match:
        raise ValueError(f"Filename does not match pattern relax_r*_m*.sc: {filename}")
    r_val = int(match.group(1))
    m_val = int(match.group(2))
    return r_val, m_val


def parse_last_score_line(sc_path: str):
    """
    Parse the last SCORE: data line from a Rosetta .sc file.

    We:
      - Identify header SCORE line (non-numeric second token)
      - Then capture SCORE lines with numeric second token (data)
      - Return header list and last data list
    """
    header = None
    last_data = None

    with open(sc_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("SCORE:"):
                continue

            tokens = line.split()
            if len(tokens) < 2:
                continue

            # Distinguish header vs data by whether tokens[1] is float
            try:
                float(tokens[1])
                # data line
                last_data = tokens[1:]
            except ValueError:
                # header line
                header = tokens[1:]

    if header is None or last_data is None:
        raise ValueError(f"Could not find both header and data SCORE lines in {sc_path}")

    if len(header) != len(last_data):
        raise ValueError(
            f"Header and data length mismatch in {sc_path}: "
            f"{len(header)} vs {len(last_data)}"
        )

    return header, last_data


def parse_runtime_from_log(log_path: str) -> float:
    """
    Parse runtime (in seconds) from a log file.

    Look for a line like:
    'protocols.jd2.JobDistributor: 1 jobs considered, 1 jobs attempted in 18 seconds'
    and return 18 as float.
    """
    runtime = None
    pattern = re.compile(r"(\d+)\s+seconds")

    with open(log_path, "r") as f:
        for line in f:
            if "protocols.jd2.JobDistributor" in line and "seconds" in line:
                m = pattern.search(line)
                if m:
                    runtime = float(m.group(1))

    if runtime is None:
        raise ValueError(f"Could not find runtime line in log file: {log_path}")

    return runtime


def main():
    # -------------------------------------------------------------------------
    # 1. Collect and parse all .sc files
    # -------------------------------------------------------------------------
    sc_files = sorted(glob.glob("relax_r*_m*.sc"))

    if len(sc_files) != 14:
        print(f"Warning: expected 14 .sc files, found {len(sc_files)}")

    rows = []
    header_cols = None

    for sc in sc_files:
        r_val, m_val = parse_r_m_from_filename(sc)
        header, data = parse_last_score_line(sc)

        if header_cols is None:
            header_cols = header
        elif header_cols != header:
            raise ValueError(f"Header mismatch across files, first vs {sc}")

        row = {col: val for col, val in zip(header, data)}
        # Convert numeric-looking values to float where possible
        for k, v in list(row.items()):
            try:
                row[k] = float(v)
            except ValueError:
                pass

        # Require total_score to exist (no fallback to 'score')
        if "total_score" not in row:
            raise KeyError(
                f"'total_score' column not found in {sc}. "
                f"Available columns: {list(row.keys())}"
            )

        # More informative column names
        row["repack_distance"] = r_val    # previously r_distance
        row["min_distance"] = m_val       # previously m_distance
        row["source_file"] = Path(sc).name

        # Corresponding log file name: flags_r{r}_m{m}.log
        log_name = f"flags_r{r_val}_m{m_val}.log"
        log_path = Path(log_name)
        if not log_path.is_file():
            raise FileNotFoundError(f"Log file not found for {sc}: {log_name}")

        runtime_seconds = parse_runtime_from_log(log_name)
        row["runtime"] = runtime_seconds

        rows.append(row)

    df = pd.DataFrame(rows)

    # sanity: 14 rows expected
    print(f"Dataframe shape: {df.shape}")
    print(df.head())

    # -------------------------------------------------------------------------
    # 2. Matplotlib settings
    # -------------------------------------------------------------------------
    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = 18

    # Two-line prefix to keep titles readable
    title_prefix = "Pab1 L55A\nCartesian optimization"

    # -------------------------------------------------------------------------
    # 3. Filter subsets for the two different sweeps
    # -------------------------------------------------------------------------
    # Repack sweep: min_distance == 10000  (6 points)
    df_repack = df[df["min_distance"] == 10000].copy()

    # Minimization sweep: repack_distance == 10000 (8 points)
    df_min = df[df["repack_distance"] == 10000].copy()

    # -------------------------------------------------------------------------
    # 4. Plot: total_score vs repack distance (6 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_repack["repack_distance"], df_repack["total_score"], s=80)
    plt.title(f"{title_prefix}\nTotal score vs repack shell distance")
    plt.xlabel("Repack shell distance (Å)")
    plt.ylabel("Total score")
    plt.tight_layout()
    plt.savefig("total_score_vs_repack_distance.png", dpi=300)

    # -------------------------------------------------------------------------
    # 5. Plot: total_score vs minimization distance (8 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_min["min_distance"], df_min["total_score"], s=80)
    plt.title(f"{title_prefix}\nTotal score vs minimization shell distance")
    plt.xlabel("Minimization shell distance (Å)")
    plt.ylabel("Total score")
    plt.tight_layout()
    plt.savefig("total_score_vs_min_distance.png", dpi=300)

    # -------------------------------------------------------------------------
    # 6. Plot: runtime vs repack distance (6 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_repack["repack_distance"], df_repack["runtime"], s=80)
    plt.title(f"{title_prefix}\nRuntime vs repack shell distance")
    plt.xlabel("Repack shell distance (Å)")
    plt.ylabel("Runtime (s)")
    plt.tight_layout()
    plt.savefig("runtime_vs_repack_distance.png", dpi=300)

    # -------------------------------------------------------------------------
    # 7. Plot: runtime vs minimization distance (8 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_min["min_distance"], df_min["runtime"], s=80)
    plt.title(f"{title_prefix}\nRuntime vs minimization shell distance")
    plt.xlabel("Minimization shell distance (Å)")
    plt.ylabel("Runtime (s)")
    plt.tight_layout()
    plt.savefig("runtime_vs_min_distance.png", dpi=300)

    # -------------------------------------------------------------------------
    # 8. Plot: runtime vs total_score for repack sweep (6 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_repack["total_score"], df_repack["runtime"], s=80)
    plt.title(f"{title_prefix}\nRuntime vs total score (repack sweep)")
    plt.xlabel("Total score")
    plt.ylabel("Runtime (s)")
    plt.tight_layout()
    plt.savefig("runtime_vs_total_score_repack.png", dpi=300)

    # -------------------------------------------------------------------------
    # 9. Plot: runtime vs total_score for minimization sweep (8 points)
    # -------------------------------------------------------------------------
    plt.figure()
    plt.scatter(df_min["total_score"], df_min["runtime"], s=80)
    plt.title(f"{title_prefix}\nRuntime vs total score (minimization sweep)")
    plt.xlabel("Total score")
    plt.ylabel("Runtime (s)")
    plt.tight_layout()
    plt.savefig("runtime_vs_total_score_min.png", dpi=300)

    print("Saved plots:")
    print("  total_score_vs_repack_distance.png")
    print("  total_score_vs_min_distance.png")
    print("  runtime_vs_repack_distance.png")
    print("  runtime_vs_min_distance.png")
    print("  runtime_vs_total_score_repack.png")
    print("  runtime_vs_total_score_min.png")

    # Optional: save dataframe as well
    df.to_csv("relax_sweep_scores_with_runtime.csv", index=False)
    print("Saved dataframe to relax_sweep_scores_with_runtime.csv")


if __name__ == "__main__":
    main()



