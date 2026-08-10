# Scheduled GACS Playwright Download

This repository runs the existing GACS Playwright automation in GitHub Actions. Every hour it downloads one more day of station reports (starting 2026-07-19, advancing a day at a time), merges the result into a running combined report, and commits that combined report straight into this repository under `data/`. It also keeps the existing GitHub Actions artifact upload for debugging.

Which day still needs downloading is worked out fresh on every run from what's actually in `data/combined_all_station_reports.xlsx` — there's no separate progress-tracking file that can fall out of sync with the real data.

## Files

- `download_gacs_reports.py` — opens GACS and downloads station reports.
- `combine_station_reports.py` — combines AIRFIELD, ALNUMAN, and TRIPLEBAY reports.
- `run_gacs_job.py` — runs the download and combination steps.
- `determine_next_date.py` — inspects `data/combined_all_station_reports.xlsx` and reports the next date that still needs downloading: today until it has a full 24 hours, or any past date where a station has zero rows (its download never actually succeeded); "nothing left" once everything through today is accounted for.
- `merge_combined_reports.py` — merges the previous combined report (`data/combined_all_station_reports.xlsx`) with the newly downloaded day, replacing that day's old rows and de-duplicating.
- `data/combined_all_station_reports.xlsx` — every processed day merged together so far, and the source of truth for what's already done. Created after the first successful run.
- `requirements.txt` — Python dependencies.
- `.github/workflows/main.yml` — the schedule, backfill, and repo-commit logic.
- `.gitignore` — prevents credentials, sessions, downloads, and logs from being committed.

## GitHub setup

### 1. Create a private repository

1. Sign in to GitHub.
2. Select **New repository**.
3. Name it, for example, `scheduled-gacs-playwright`.
4. Select **Private**.
5. Create the repository without adding a README or `.gitignore` because they are already included here.

### 2. Upload this project

Extract this ZIP. Upload the contents of the `scheduled-playwright` folder to the root of the new repository.

The repository root must show:

```text
.github/
combine_station_reports.py
download_gacs_reports.py
run_gacs_job.py
requirements.txt
README.md
.gitignore
```

Do not upload the parent folder as an extra level. The `.github` folder must be directly in the repository root.

### 3. Add the login secrets

In the GitHub repository:

1. Open **Settings**.
2. Open **Secrets and variables**.
3. Select **Actions**.
4. Select **New repository secret**.
5. Create `GACS_EMAIL` and enter the GACS login email.
6. Create `GACS_PASSWORD` and enter the GACS password.

The secret names must match exactly, including capital letters. No other secrets or external accounts are needed — results are committed straight into this repository using the workflow's built-in `GITHUB_TOKEN` (the workflow already grants it `contents: write`).

### 4. Run the first test manually

1. Open the repository's **Actions** tab.
2. Select **Scheduled GACS Playwright Download**.
3. Select **Run workflow**.
4. Leave both date fields empty to let it pick up the next backfill day automatically (starting 2026-07-19), or enter dates in `YYYY-MM-DD` format to force a specific one-off range (this does not touch the saved backfill progress).
5. Select **Run workflow**.
6. Open the running job and review each step.

### 5. Get the result

After every run that added or refreshed data, the workflow commits `data/combined_all_station_reports.xlsx` straight into this repository's default branch — every processed day merged together so far. Just `git pull`, or browse to `data/` on GitHub, to get the latest file — no separate download step needed.

The GitHub Actions artifact (`gacs-results-<run number>`, under **Artifacts** on the run page) still contains that run's individual station folders, diagnostics, and `gacs_job.log`, for debugging a single run.

## Current schedule

The workflow runs **every hour** (`0 * * * *`). GitHub does not reliably honor `schedule:` triggers more frequent than about once an hour regardless of the cron value used, so this is effectively the fastest cadence that actually fires close to on time.

Each run asks `determine_next_date.py` which day still needs work, starting from **2026-07-19**, using two different rules:

- **Today** needs a full 24 hours for every station before it's considered done — today can legitimately keep gaining hours as real time passes, so it's re-downloaded and re-merged (replacing its old rows) every hour until it reaches 24 or the day ends.
- **A past day** (already fully elapsed) is considered done as soon as every station has *any* successfully downloaded rows for it — a finished day's data is whatever the sensors recorded in one shot; asking again won't produce more hours, so a day that genuinely only has, say, 18 hours because of a real sensor gap is accepted as-is rather than retried forever. Only a station with **zero** rows for a past date — meaning its download never actually succeeded — gets retried.

Once every day through today is accounted for, the run does nothing. This makes hourly a good steady-state cadence, not just a temporary backfill one — no need to change it once caught up. Runs are queued (not run in parallel) so `data/` is never read/written by two runs at once.

Because completeness is checked against the real data instead of a separate marker, this also self-heals: if a past day's download ever failed outright (zero rows), it's automatically retried on the next run rather than needing a manual fix.

To use a different cadence, edit the `cron:` value in `.github/workflows/main.yml`. Examples:

- `"30 8 * * *"` — daily at 08:30 UTC.
- `"0 */6 * * *"` — every six hours.
- `"15 9 * * 0"` — Sunday at 09:15.

### Reprocessing a day

To force a day to be re-downloaded, delete its rows for that date from `data/combined_all_station_reports.xlsx` (or delete the whole file to restart the backfill from 2026-07-19) — the next run will treat it as incomplete and fetch it again.

## Important limitations

The run will fail if GACS requires CAPTCHA, manual MFA approval, an internal company VPN, or an allow-listed company IP address. A normal public login using email and password should work with the included setup.

If the first run fails, download the artifact anyway. The automation saves logs, HTML diagnostics, and screenshots that identify where the website flow stopped.
"# Amaala-Met" 
