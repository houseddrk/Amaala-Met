from datetime import date, timedelta
from pathlib import Path
import argparse

import pandas as pd

DEFAULT_START_DATE = date(2026, 7, 19)
EXPECTED_STATIONS = ("AIRFIELD", "ALNUMAN", "TRIPLEBAY")
EXPECTED_HOURS_PER_DAY = 24


def load_combined(path):
    if not path.exists():
        return None
    return pd.read_excel(path, engine="openpyxl")


def has_any_data(df, report_date):
    """Whether every station has at least one successfully downloaded row for
    this date. Used for past days: a finished day's data is whatever the
    sensors recorded, obtained in a single successful download -- asking
    again won't produce more hours, so a day with real (even partial) data
    is done. Zero rows for a station means the download itself never
    succeeded, which is worth retrying.
    """
    if df is None:
        return False

    day_rows = df[df["ReportDate"] == report_date]
    if day_rows.empty:
        return False

    return all(
        not day_rows[day_rows["Station"] == station].empty
        for station in EXPECTED_STATIONS
    )


def is_full_day(df, report_date):
    """Whether every station has a full day of hours. Used only for today,
    which can legitimately keep gaining hours as real time passes.
    """
    if df is None:
        return False

    day_rows = df[df["ReportDate"] == report_date]
    if day_rows.empty:
        return False

    for station in EXPECTED_STATIONS:
        station_rows = day_rows[day_rows["Station"] == station]
        if station_rows["Time"].nunique() < EXPECTED_HOURS_PER_DAY:
            return False

    return True


def find_next_date(df, today):
    candidate = DEFAULT_START_DATE

    while candidate < today:
        if not has_any_data(df, candidate.isoformat()):
            return candidate
        candidate += timedelta(days=1)

    if is_full_day(df, candidate.isoformat()):
        candidate += timedelta(days=1)

    return candidate


def build_parser():
    parser = argparse.ArgumentParser(
        description="Find the next date that needs downloading, based on what's actually "
        "in the combined report rather than a separately tracked marker file."
    )
    parser.add_argument("--combined", type=Path, required=True, help="Path to the combined report file.")
    parser.add_argument("--today", required=True, help="Today's date (YYYY-MM-DD) in the target timezone.")
    return parser


def main():
    args = build_parser().parse_args()
    today = date.fromisoformat(args.today)
    df = load_combined(args.combined)

    candidate = find_next_date(df, today)

    if candidate > today:
        print("skip=true")
        return

    print("skip=false")
    print(f"date={candidate.isoformat()}")
    print(f"is_today={'true' if candidate == today else 'false'}")


if __name__ == "__main__":
    main()
