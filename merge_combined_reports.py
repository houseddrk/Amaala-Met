from pathlib import Path
import argparse

import pandas as pd

from report_columns import normalize_report_columns, order_columns

SORT_COLUMNS = ["Station", "ReportDate", "Time"]


def load(path):
    if not path.exists():
        return None
    return normalize_report_columns(pd.read_excel(path, engine="openpyxl"))


def merge(previous_path, new_path, output_path, replace_date=None):
    previous_df = load(previous_path)
    new_df = load(new_path)

    if new_df is None:
        raise SystemExit(f"New combined file not found: {new_path}")

    if previous_df is None:
        merged = new_df
    else:
        if replace_date and "ReportDate" in previous_df.columns:
            previous_df = previous_df[previous_df["ReportDate"] != replace_date]
        merged = pd.concat([previous_df, new_df], ignore_index=True, sort=False)

    merged = normalize_report_columns(merged).drop_duplicates()

    sort_columns = [column for column in SORT_COLUMNS if column in merged.columns]
    if sort_columns:
        merged = merged.sort_values(sort_columns).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    order_columns(merged).to_excel(output_path, index=False)

    print(f"Merged rows: {len(merged)}")
    print(f"Created: {output_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Merge a previous combined report with a newly generated one, de-duplicating rows."
    )
    parser.add_argument("--previous", type=Path, required=True, help="Previous combined file (may not exist).")
    parser.add_argument("--new", type=Path, required=True, help="Newly generated combined file.")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the merged file to.")
    parser.add_argument(
        "--replace-date",
        help="Drop existing rows for this ReportDate (YYYY-MM-DD) from --previous before merging, "
        "so a re-processed in-progress day is replaced rather than appended to.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    merge(args.previous, args.new, args.output, replace_date=args.replace_date)


if __name__ == "__main__":
    main()
