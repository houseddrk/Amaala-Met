from datetime import date, datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys

from gacs_env import load_env_file


SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "gacs_job.log"

load_env_file(SCRIPT_DIR / ".env")

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

START_DATE = os.environ.get("GACS_START_DATE") or YESTERDAY
END_DATE = os.environ.get("GACS_END_DATE") or START_DATE
REPORT_TIMEOUT_SECONDS = os.environ.get("GACS_REPORT_TIMEOUT_SECONDS") or "60"

RUN_ID = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"

    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(formatted_message + "\n")

    print(formatted_message, flush=True)


def run_command(command: list[str]) -> bool:
    log(f"Running: {' '.join(command)}")

    result = subprocess.run(
        command,
        cwd=SCRIPT_DIR,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    if result.stdout:
        log("STDOUT:")
        print(result.stdout, flush=True)

        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(result.stdout)
            if not result.stdout.endswith("\n"):
                file.write("\n")

    if result.stderr:
        log("STDERR:")
        print(result.stderr, file=sys.stderr, flush=True)

        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(result.stderr)
            if not result.stderr.endswith("\n"):
                file.write("\n")

    if result.returncode != 0:
        log(f"ERROR: command failed with exit code {result.returncode}")
        return False

    log("Command completed successfully.")
    return True


def finish_run(status: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(
            f"RUN END: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"- {status}\n"
        )


def main() -> int:
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write("\n")
        file.write("=" * 80 + "\n")
        file.write(f"RUN START: {RUN_ID}\n")
        file.write("=" * 80 + "\n")

    log("Starting GACS scheduled job.")
    log(f"Date range: {START_DATE} to {END_DATE}")
    log(f"Report timeout seconds: {REPORT_TIMEOUT_SECONDS}")

    if not os.environ.get("GACS_EMAIL") or not os.environ.get("GACS_PASSWORD"):
        log(
            "ERROR: GACS_EMAIL and GACS_PASSWORD "
            "environment variables are required."
        )
        finish_run("FAILED")
        return 1

    download_command = [
        sys.executable,
        str(SCRIPT_DIR / "download_gacs_reports.py"),
        "--station-folder",
        "--start-date",
        START_DATE,
        "--end-date",
        END_DATE,
        "--report-timeout-seconds",
        REPORT_TIMEOUT_SECONDS,
        "--download-retries",
        "3",
        "--overwrite-existing",
        "--non-interactive",
        "--headless",
    ]

    if not run_command(download_command):
        log("Download command failed. Skipping combine step.")
        finish_run("FAILED")
        return 1

    combine_command = [
        sys.executable,
        str(SCRIPT_DIR / "combine_station_reports.py"),
    ]

    if not run_command(combine_command):
        log("Combine command failed.")
        finish_run("FAILED")
        return 1

    log("GACS scheduled job finished successfully.")
    finish_run("SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
