from datetime import datetime, timezone
from pathlib import Path
import argparse


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "missing_gacs_reports.txt"


def read_existing_lines(path):
    if not path.exists():
        return set()
    return set(path.read_text(encoding="utf-8").splitlines())


def collect_skipped_lines(report_date, run_status, output_path):
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = []

    for skipped_file in sorted(SCRIPT_DIR.glob("*_gacs_downloads/*_skipped_days.txt")):
        for raw_line in skipped_file.read_text(encoding="utf-8").splitlines():
            parts = raw_line.split("\t", 2)
            if len(parts) != 3:
                continue

            skipped_date, station, reason = parts
            if report_date and skipped_date != report_date:
                continue

            lines.append(
                "\t".join(
                    [
                        run_at,
                        skipped_date,
                        station,
                        run_status,
                        reason,
                    ]
                )
            )

    if not lines and report_date and run_status != "success":
        lines.append(
            "\t".join(
                [
                    run_at,
                    report_date,
                    "ALL_STATIONS",
                    run_status,
                    "The workflow failed before station-level skipped reports were created.",
                ]
            )
        )

    if not lines:
        print("No missing reports to log.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = read_existing_lines(output_path)
    new_lines = [line for line in lines if line not in existing_lines]

    if not new_lines:
        print("Missing reports already logged.")
        return

    with output_path.open("a", encoding="utf-8") as file:
        if output_path.stat().st_size == 0:
            file.write("RunAtUTC\tReportDate\tStation\tRunStatus\tReason\n")
        for line in new_lines:
            file.write(line + "\n")

    print(f"Logged missing reports: {len(new_lines)}")
    print(f"Updated: {output_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Append skipped GACS station reports to one persistent log file."
    )
    parser.add_argument("--date", help="Report date to collect, in YYYY-MM-DD format.")
    parser.add_argument(
        "--run-status",
        default="success",
        help="Workflow/script status, for example success or failure.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main():
    args = build_parser().parse_args()
    output = args.output
    if not output.is_absolute():
        output = SCRIPT_DIR / output
    collect_skipped_lines(args.date, args.run_status, output)


if __name__ == "__main__":
    main()
