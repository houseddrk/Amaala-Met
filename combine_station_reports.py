from pathlib import Path
import re
import sys

import pandas as pd

from report_columns import normalize_report_columns, order_columns

STATION_FOLDERS = (
    Path("AIRFIELD_gacs_downloads"),
    Path("ALNUMAN_gacs_downloads"),
    Path("TRIPLEBAY_gacs_downloads"),
)
OUTPUT_FILE = Path("combined_all_station_reports.xlsx")


def station_from_folder(folder):
    return folder.name.replace("_gacs_downloads", "")


def report_date_from_filename(path, station):
    match = re.match(rf"^{re.escape(station)}_(\d{{4}}-\d{{2}}-\d{{2}})$", path.stem)
    return match.group(1) if match else ""


def read_report(path):
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path, engine="openpyxl")

    return normalize_report_columns(df)


def main():
    frames = []

    for folder in STATION_FOLDERS:
        if not folder.exists():
            print(f"Missing folder: {folder}")
            continue

        station = station_from_folder(folder)
        files = sorted(
            path
            for path in folder.iterdir()
            if path.suffix.lower() in {".csv", ".xlsx", ".xls"}
            and path.name.startswith(f"{station}_")
        )

        for path in files:
            try:
                df = read_report(path)
            except Exception as exc:
                print(f"Could not read {path}: {exc}")
                continue

            df.insert(0, "Station", station)
            df.insert(1, "ReportDate", report_date_from_filename(path, station))
            frames.append(df)

    if not frames:
        print("No reports found to combine.")
        return 0

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = order_columns(combined)
    combined.to_excel(OUTPUT_FILE, index=False)
    print(f"Created: {OUTPUT_FILE}")
    print(f"Rows: {len(combined)}")
    print(f"Columns: {len(combined.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
