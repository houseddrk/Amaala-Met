from datetime import date, timedelta
from pathlib import Path
import argparse
import csv
import os
import re
import sys
import time

from gacs_env import load_env_file

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    PlaywrightTimeoutError = None
    sync_playwright = None

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None


SCRIPT_DIR = Path(__file__).resolve().parent
load_env_file(SCRIPT_DIR / ".env")

BASE_URL = "https://www.gacscloud.com/"
DEFAULT_START_DATE = date(2026, 1, 1)
DEFAULT_END_DATE = date.today()
DEFAULT_DOWNLOAD_DIR = SCRIPT_DIR / "gacs_downloads"
DEFAULT_SESSION_FILE = SCRIPT_DIR / "gacs_session.json"
DEFAULT_WAIT_SECONDS = 0
DEFAULT_REPORT_TIMEOUT_SECONDS = 20
DEFAULT_MIN_COLUMNS = 0
DEFAULT_DOWNLOAD_RETRIES = 2

REPORT_BUTTON_XPATH = "/html/body/app-root/app-amaala-dashboard/nav/div/form/button[1]"
REPORT_BUTTON_SELECTORS = (
    f"xpath={REPORT_BUTTON_XPATH}",
    "app-amaala-dashboard nav form button",
    "nav form button",
    "button:has-text('Report')",
    "button:has-text('Reports')",
    "a:has-text('Report')",
    "a:has-text('Reports')",
)
LOGIN_SELECTORS = (
    "a.login",
    "a:has-text('LOGIN')",
    "button:has-text('LOGIN')",
    "text=LOGIN",
)
STATION_DROPDOWN = "select#StationDropdown"
PERIOD_DROPDOWN = "select#period"
START_DATE_INPUT = "input#start_date"
RUN_BUTTON_XPATH = "/html/body/app-root/app-report-filters/section/div[2]/div/div[1]/div/div/div/form/div[3]/div[2]/div/div/input"
RUN_BUTTON_SELECTORS = (
    "input[type='button'][value='Generate Report']",
    "input[value='Generate Report']",
    "text=Generate Report",
    f"xpath={RUN_BUTTON_XPATH}",
)
DOWNLOAD_XPATH = "/html/body/app-root/app-report-filters/section/div[2]/div/div[2]/div/div/div/div[2]/div/a[3]"
DOWNLOAD_SELECTORS = (
    "a:has-text('Download Hourly')",
    "text=Download Hourly",
    f"xpath={DOWNLOAD_XPATH}",
)

SUPPORTED_DOWNLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")


def clean_filename(text):
    cleaned = re.sub(r"[^\w\-]+", "_", text).strip("_")
    return cleaned or "station"


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid date. Use YYYY-MM-DD."
        ) from exc


def daterange(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def count_report_columns(path):
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as file:
            return len(next(csv.reader(file), []))

    if pd is None:
        return 0

    return len(pd.read_excel(path, nrows=0, engine="openpyxl").columns)


def report_is_complete(path, min_columns):
    if min_columns <= 0:
        return True

    try:
        return count_report_columns(path) >= min_columns
    except Exception:
        return False


def require_playwright():
    if sync_playwright is None:
        raise SystemExit(
            "Missing dependency: playwright\n"
            "Install it with:\n"
            "  python3 -m pip install -r requirements.txt\n"
            "  python3 -m playwright install chromium"
        )


def require_pandas():
    if pd is None:
        raise SystemExit(
            "Missing dependency: pandas\n"
            "Install it with:\n"
            "  python3 -m pip install -r requirements.txt"
        )


def save_login_session(base_url, session_file, headless, interactive=True):
    require_playwright()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        page.goto(base_url, wait_until="domcontentloaded")
        wait_for_page_to_settle(page)
        login_with_env_or_prompt(page, interactive=interactive)

        wait_for_page_to_settle(page)
        if is_public_home_page(page):
            screenshot, html = save_page_diagnostics(
                page,
                DEFAULT_DOWNLOAD_DIR,
                "login_not_completed",
            )
            browser.close()
            raise SystemExit(
                "Login was not completed, so the session was not saved.\n"
                "The browser was still on the public GACS home/login page.\n"
                f"Saved screenshot: {screenshot}\n"
                f"Saved HTML: {html}\n"
                "Run `python3 download_gacs_reports.py --login-only` again, "
                "fill the email/password in the login popup, click Submit, "
                "wait for the dashboard, then press ENTER in Terminal."
            )

        context.storage_state(path=session_file)
        browser.close()

    print(f"Login session saved to {session_file}.")


def prompt_for_login(page, context, session_file, interactive):
    login_with_env_or_prompt(page, interactive=interactive)

    context.storage_state(path=session_file)
    print(f"Login session saved to {session_file}.")


def login_with_env_or_prompt(page, interactive=True):
    open_login_modal_if_needed(page)

    if login_modal_is_open(page) and fill_login_from_env(page):
        wait_for_page_to_settle(page)
        if not is_public_home_page(page):
            return

    if not interactive:
        raise RuntimeError(
            "GACS login is required, but automatic login failed and "
            "--non-interactive is enabled. Check GACS_EMAIL/GACS_PASSWORD "
            "or refresh gacs_session.json manually."
        )

    print("GACS is asking for login.")
    print("Sign in in the opened browser, wait for the dashboard, then press ENTER here.")
    input()

    wait_for_page_to_settle(page)
    if is_public_home_page(page):
        raise RuntimeError(
            "Login was not completed. The browser is still on the public "
            "GACS home/login page."
        )


def fill_login_from_env(page):
    email = os.environ.get("GACS_EMAIL")
    password = os.environ.get("GACS_PASSWORD")

    if not email or not password:
        return False

    try:
        email_input = page.locator("input[placeholder='Enter email']").nth(0)
        password_input = page.locator("input[placeholder='Enter password']").nth(0)

        email_input.fill(email)
        password_input.fill(password)

        submit_button = page.locator("button[type='submit']").nth(0)
        submit_button.click(timeout=10000)

        page.locator("input[placeholder='Enter email']").nth(0).wait_for(
            state="hidden",
            timeout=30000,
        )
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False

    return True


def wait_for_page_to_settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass


def first_visible_locator(page, selectors, timeout=3000):
    for selector in selectors:
        locator = page.locator(selector).nth(0)
        try:
            locator.wait_for(state="visible", timeout=timeout)
            return locator
        except PlaywrightTimeoutError:
            continue

    return None


def first_visible_locator_until(page, selectors, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        for selector in selectors:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return None

            locator = page.locator(selector).nth(0)
            try:
                locator.wait_for(
                    state="visible",
                    timeout=min(1000, remaining_ms),
                )
                return locator
            except PlaywrightTimeoutError:
                continue

    return None


def append_skipped_day(download_dir, station_label, date_text, reason):
    skipped_file = download_dir / f"{station_label}_skipped_days.txt"
    message = " ".join(str(reason).split())
    remove_skipped_day(download_dir, station_label, date_text)
    with skipped_file.open("a", encoding="utf-8") as file:
        file.write(f"{date_text}\t{station_label}\t{message}\n")
    return skipped_file


def remove_skipped_day(download_dir, station_label, date_text):
    skipped_file = download_dir / f"{station_label}_skipped_days.txt"
    if not skipped_file.exists():
        return False

    lines = skipped_file.read_text(encoding="utf-8").splitlines()
    prefix = f"{date_text}\t{station_label}\t"
    kept_lines = [line for line in lines if not line.startswith(prefix)]

    if len(kept_lines) == len(lines):
        return False

    if kept_lines:
        skipped_file.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
    else:
        skipped_file.unlink()

    return True


def remove_failure_screenshot(download_dir, station_label, date_text):
    failure_file = download_dir / f"{station_label}_failures" / f"{station_label}_{date_text}.png"
    if failure_file.exists():
        failure_file.unlink()
        return True
    return False


def clear_failure_records(download_dir, station_label, date_text):
    removed_skipped = remove_skipped_day(download_dir, station_label, date_text)
    removed_screenshot = remove_failure_screenshot(download_dir, station_label, date_text)
    if removed_skipped or removed_screenshot:
        print(f"Cleared old failure record: {station_label} - {date_text}")


def is_public_home_page(page):
    try:
        if login_modal_is_open(page):
            return True

        if page.locator("app-home-page").count() == 0:
            return False

        return first_visible_locator(page, LOGIN_SELECTORS, timeout=500) is not None
    except Exception:
        return False


def open_login_modal_if_needed(page):
    if login_modal_is_open(page):
        return

    if not is_public_home_page(page):
        return

    login_link = first_visible_locator(page, LOGIN_SELECTORS, timeout=5000)
    if login_link is None:
        return

    try:
        login_link.click(timeout=10000)
    except PlaywrightTimeoutError:
        if login_modal_is_open(page):
            return
        raise

    wait_for_login_modal(page)


def login_modal_is_open(page):
    try:
        email_input = page.locator("input[placeholder='Enter email']").nth(0)
        email_input.wait_for(state="visible", timeout=500)
        return True
    except PlaywrightTimeoutError:
        return False


def wait_for_login_modal(page):
    try:
        page.locator("input[placeholder='Enter email']").wait_for(
            state="visible",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        pass


def visible_page_summary(page):
    try:
        buttons = page.locator("button, a").evaluate_all(
            """
            elements => elements
                .map(element => element.textContent.trim())
                .filter(Boolean)
                .slice(0, 30)
            """
        )
    except Exception:
        buttons = []

    try:
        title = page.title()
    except Exception:
        title = ""

    return {
        "url": page.url,
        "title": title,
        "buttons_and_links": buttons,
    }


def save_page_diagnostics(page, download_dir, name):
    download_dir.mkdir(parents=True, exist_ok=True)
    screenshot = download_dir / f"{name}.png"
    html = download_dir / f"{name}.html"

    page.screenshot(path=screenshot, full_page=True)
    html.write_text(page.content(), encoding="utf-8")

    return screenshot, html


def open_report_page(page, context, args):
    wait_for_page_to_settle(page)

    if is_public_home_page(page):
        prompt_for_login(page, context, args.session_file, interactive=not args.non_interactive)
        wait_for_page_to_settle(page)

    if page.locator(STATION_DROPDOWN).count() > 0:
        try:
            page.locator(STATION_DROPDOWN).nth(0).wait_for(
                state="visible",
                timeout=5000,
            )
            return
        except PlaywrightTimeoutError:
            pass

    report_button = first_visible_locator(page, REPORT_BUTTON_SELECTORS)

    if report_button is None:
        screenshot, html = save_page_diagnostics(
            page,
            args.download_dir,
            "open_report_page_failed",
        )
        summary = visible_page_summary(page)
        raise RuntimeError(
            "Could not find the report button after opening GACS.\n"
            f"Current URL: {summary['url']}\n"
            f"Page title: {summary['title']}\n"
            f"Visible buttons/links: {summary['buttons_and_links']}\n"
            f"Saved screenshot: {screenshot}\n"
            f"Saved HTML: {html}\n"
            "If the screenshot shows the login page, rerun this command and "
            "sign in when prompted."
        )

    report_button.click(timeout=30000)
    wait_for_page_to_settle(page)
    page.wait_for_selector(STATION_DROPDOWN, timeout=60000)


def get_raw_stations(page):
    stations = page.locator(f"{STATION_DROPDOWN} option").evaluate_all(
        """
        options => options
            .map((o, index) => ({
                option_index: index + 1,
                value: o.value,
                label: o.textContent.trim(),
                disabled: o.disabled,
                selected: o.selected
            }))
            .filter(o => o.value && o.value.trim() !== "")
        """
    )
    return stations


def unique_stations(stations):
    unique = []
    seen = set()
    for station in stations:
        key = (station["value"], station["label"])
        if key in seen:
            continue

        seen.add(key)
        unique.append(station)

    return unique


def get_stations(page):
    stations = []
    usable_stations = []

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        stations = get_raw_stations(page)
        usable_stations = [
            station
            for station in stations
            if not station["disabled"] and station["value"].strip().lower() != "none"
        ]
        if usable_stations:
            break
        time.sleep(1)

    disabled_stations = [
        station
        for station in stations
        if station["disabled"] or station["value"].strip().lower() == "none"
    ]

    if disabled_stations:
        names = ", ".join(station["label"] for station in disabled_stations)
        print(f"Skipping disabled stations: {names}")

    if not usable_stations:
        options = ", ".join(
            f"option[{station['option_index']}] "
            f"{station['label']} value={station['value']} "
            f"disabled={station['disabled']}"
            for station in stations
        )
        raise RuntimeError(
            "No usable stations found in the station dropdown after waiting 60 seconds. "
            f"Options seen: {options or 'none'}"
        )

    return unique_stations(usable_stations)


def print_stations(page):
    raw_stations = unique_stations(get_raw_stations(page))
    if not raw_stations:
        print("No station options found.")
        return

    for index, station in enumerate(raw_stations, start=1):
        flags = []
        if station["selected"]:
            flags.append("selected")
        if station["disabled"]:
            flags.append("disabled")

        suffix = f" ({', '.join(flags)})" if flags else ""
        print(
            f"{index}. option[{station['option_index']}] "
            f"{station['label']} [value={station['value']}]{suffix}"
        )


def select_daily_period(page):
    period = page.locator(PERIOD_DROPDOWN)

    for option in ({"label": "Daily"}, {"label": "daily"}, {"value": "daily"}):
        try:
            period.select_option(**option, timeout=10000)
            return
        except Exception:
            continue

    available = page.locator(f"{PERIOD_DROPDOWN} option").evaluate_all(
        "options => options.map(o => `${o.value}:${o.textContent.trim()}`)"
    )
    raise RuntimeError(f"Could not select Daily period. Available options: {available}")


def set_date(page, date_text):
    field = page.locator(START_DATE_INPUT)
    field.wait_for(state="visible", timeout=30000)
    field.fill(date_text)
    field.evaluate(
        """
        (element, value) => {
            element.value = value;
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        date_text,
    )


def select_all_report_fields(page):
    select_all = page.locator("text=Select All").first
    try:
        if select_all.is_visible(timeout=3000):
            select_all.click(timeout=10000)
            time.sleep(1)
    except Exception:
        pass

    checkboxes = page.locator("input[type='checkbox']")
    for index in range(checkboxes.count()):
        checkbox = checkboxes.nth(index)
        try:
            if checkbox.is_enabled() and not checkbox.is_checked():
                checkbox.check(force=True, timeout=5000)
        except Exception:
            continue


def uncheck_report_field(page, field_label):
    selectors = (
        f"label:has-text('{field_label}') input[type='checkbox']",
        f"xpath=//*[normalize-space()='{field_label}']/preceding::input[@type='checkbox'][1]",
        f"xpath=//*[contains(normalize-space(), '{field_label}')]/preceding::input[@type='checkbox'][1]",
    )

    for selector in selectors:
        checkbox = page.locator(selector).first
        try:
            if checkbox.count() and checkbox.is_enabled() and checkbox.is_checked():
                checkbox.uncheck(force=True, timeout=5000)
                return True
        except Exception:
            continue

    return False


def apply_station_report_field_rules(page, station_label):
    if clean_filename(station_label).lower() == "airfield":
        if uncheck_report_field(page, "Cloud Cover"):
            print("Unchecked AIRFIELD-only field: Cloud Cover")
        else:
            print("Could not find AIRFIELD-only field to uncheck: Cloud Cover")


def report_date_text_options(date_text):
    report_date = date.fromisoformat(date_text)
    return (
        report_date.strftime("%m/%d/%Y"),
        report_date.strftime("%d/%m/%Y"),
    )


def wait_for_report_ready(page, date_text, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    expected_texts = [
        f"Report for - {date_text_option}"
        for date_text_option in report_date_text_options(date_text)
    ]

    while time.monotonic() < deadline:
        for expected in expected_texts:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break

            try:
                page.locator(f"text={expected}").wait_for(
                    state="visible",
                    timeout=min(1000, remaining_ms),
                )
                return
            except PlaywrightTimeoutError:
                continue

    raise RuntimeError(
        "Report page did not update to one of "
        f"{expected_texts!r} within {timeout_seconds} seconds."
    )


def wait_for_station_option(page, station, timeout_seconds=60):
    deadline = time.monotonic() + timeout_seconds
    last_options = []

    while time.monotonic() < deadline:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break

        page.wait_for_selector(STATION_DROPDOWN, timeout=min(1000, remaining_ms))
        option_state = page.locator(STATION_DROPDOWN).evaluate(
            """
            (select, details) => {
                const options = Array.from(select.options).map((option, index) => ({
                    option_index: index + 1,
                    value: option.value,
                    label: option.textContent.trim(),
                    disabled: option.disabled,
                    selected: option.selected
                }));
                const byIndex = options.find(
                    option => option.option_index === details.optionIndex
                );
                if (byIndex && byIndex.value === details.value) {
                    return { match: byIndex, options };
                }

                const byValue = options.find(option => option.value === details.value);
                return { match: byValue || null, options };
            }
            """,
            {
                "optionIndex": station["option_index"],
                "value": station["value"],
            },
        )
        last_options = option_state["options"]
        if option_state["match"]:
            return option_state["match"]

        time.sleep(1)

    options = ", ".join(
        f"option[{option['option_index']}] {option['label']} "
        f"value={option['value']} disabled={option['disabled']}"
        for option in last_options
    )
    raise RuntimeError(
        f"Station {station['label']!r} value={station['value']} was not found "
        f"after waiting {timeout_seconds} seconds. Options seen: {options or 'none'}"
    )


def prepare_report_form(page, station, date_text):
    station_value = station["value"]
    station_state = wait_for_station_option(page, station)
    option_index = station_state["option_index"]

    if station_state["disabled"] and not station_state["selected"]:
        raise RuntimeError(f"Station option index {option_index} is disabled.")

    if not station_state["selected"]:
        page.locator(f"xpath=//*[@id='StationDropdown']/option[{option_index}]").evaluate(
            """
            option => {
                option.selected = true;
                option.parentElement.dispatchEvent(new Event('input', { bubbles: true }));
                option.parentElement.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """
        )
        page.locator(STATION_DROPDOWN).evaluate(
            """
            (select, value) => {
                if (select.value !== value) {
                    throw new Error(`Station did not switch. Current=${select.value}, expected=${value}`);
                }
            }
            """,
            station_value,
        )

    select_daily_period(page)
    set_date(page, date_text)
    select_all_report_fields(page)
    apply_station_report_field_rules(page, station["label"])


def download_one_report(
    page,
    context,
    args,
    station,
    date_text,
    output_base,
    wait_seconds,
    report_timeout_seconds,
    min_columns,
    download_retries,
):
    prepare_report_form(page, station, date_text)

    last_error = None
    for attempt in range(1, download_retries + 1):
        run_button = first_visible_locator(page, RUN_BUTTON_SELECTORS, timeout=10000)
        if run_button is None:
            raise RuntimeError("Could not find the Generate Report button.")

        if download_retries > 1:
            print(f"Download attempt {attempt}/{download_retries}")

        run_button.click(timeout=30000)

        if wait_seconds:
            print(f"Waiting {wait_seconds} seconds before checking for download")
            time.sleep(wait_seconds)

        print(f"Waiting up to {report_timeout_seconds} seconds for download link")
        try:
            wait_for_report_ready(page, date_text, report_timeout_seconds)
            download_link = first_visible_locator_until(
                page,
                DOWNLOAD_SELECTORS,
                timeout_seconds=report_timeout_seconds,
            )
        except Exception as exc:
            last_error = str(exc)
            print("Report title did not appear; checking for download link directly.")
            download_link = first_visible_locator_until(
                page,
                DOWNLOAD_SELECTORS,
                timeout_seconds=10,
            )

        if download_link is None:
            last_error = (
                last_error
                or f"Download link did not appear within {report_timeout_seconds} seconds."
            )
            if attempt < download_retries:
                print("Report generation timed out; reopening report form before retry.")
                reload_report_page(page, context, args)
                prepare_report_form(page, station, date_text)
                time.sleep(2)
                continue
            continue

        with page.expect_download(timeout=report_timeout_seconds * 1000) as download_info:
            download_link.click(timeout=30000)

        download = download_info.value
        failure = download.failure()
        if failure:
            last_error = f"Download failed: {failure}"
            continue

        suggested_filename = download.suggested_filename
        extension = Path(suggested_filename).suffix.lower()
        if extension not in SUPPORTED_DOWNLOAD_EXTENSIONS:
            last_error = (
                "Downloaded file is not a supported report file. "
                f"Suggested filename: {suggested_filename}"
            )
            continue

        output_file = output_base.with_suffix(extension)
        download.save_as(output_file)

        if report_is_complete(output_file, min_columns):
            return output_file

        actual_columns = count_report_columns(output_file)
        last_error = (
            f"Downloaded report has {actual_columns} columns; "
            f"expected at least {min_columns}."
        )
        output_file.unlink(missing_ok=True)
        time.sleep(2)

    raise RuntimeError(last_error or "Report download failed.")


def save_failure_screenshot(page, download_dir, station_label, date_text):
    screenshot_dir = download_dir / f"{station_label}_failures"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot = screenshot_dir / f"{station_label}_{date_text}.png"
    page.screenshot(path=screenshot, full_page=True)
    return screenshot


def select_requested_stations(stations, args):
    if args.station_name:
        requested = clean_filename(args.station_name).lower()
        matches = [
            station
            for station in stations
            if clean_filename(station["label"]).lower() == requested
        ]
        if not matches:
            available = ", ".join(station["label"] for station in stations)
            raise RuntimeError(
                f"Station {args.station_name!r} was not found. "
                f"Available stations: {available}"
            )
        return matches

    if args.station_number is not None:
        if args.station_number < 1 or args.station_number > len(stations):
            available = ", ".join(
                f"{index + 1}:{station['label']}"
                for index, station in enumerate(stations)
            )
            raise RuntimeError(
                f"--station-number must be between 1 and {len(stations)}. "
                f"Available stations: {available}"
            )
        return [stations[args.station_number - 1]]

    if args.first_station_only:
        return stations[:1]

    return stations


def station_download_dir(base_download_dir, station_label, station_folder):
    if not station_folder:
        return base_download_dir

    return base_download_dir.parent / f"{station_label}_gacs_downloads"


def reload_report_page(page, context, args):
    page.goto(args.base_url, wait_until="domcontentloaded")
    open_report_page(page, context, args)


def download_reports(args):
    require_playwright()
    if not args.station_folder:
        args.download_dir.mkdir(parents=True, exist_ok=True)
    used_download_dirs = []

    if not args.session_file.exists():
        save_login_session(
            args.base_url,
            args.session_file,
            args.headless,
            interactive=not args.non_interactive,
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            storage_state=args.session_file,
            accept_downloads=True,
        )
        page = context.new_page()

        try:
            page.goto(args.base_url, wait_until="domcontentloaded")
            open_report_page(page, context, args)
            if args.list_stations:
                print_stations(page)
                return []

            stations = get_stations(page)
            stations = select_requested_stations(stations, args)

            print(f"Found {len(stations)} stations")

            for station_index, station in enumerate(stations):
                station_label = clean_filename(station["label"])
                current_download_dir = station_download_dir(
                    args.download_dir,
                    station_label,
                    args.station_folder,
                )
                current_download_dir.mkdir(parents=True, exist_ok=True)
                if current_download_dir not in used_download_dirs:
                    used_download_dirs.append(current_download_dir)

                print(f"\nStation: {station['label']}")
                print(f"Folder: {current_download_dir}")

                for current_date in daterange(args.start_date, args.end_date):
                    date_text = current_date.strftime("%Y-%m-%d")
                    print(f"\nDate: {date_text}")
                    output_base = current_download_dir / f"{station_label}_{date_text}"
                    existing_files = [
                        output_base.with_suffix(extension)
                        for extension in SUPPORTED_DOWNLOAD_EXTENSIONS
                        if output_base.with_suffix(extension).exists()
                    ]
                    complete_existing_files = [
                        file
                        for file in existing_files
                        if report_is_complete(file, args.min_columns)
                    ]
                    incomplete_existing_files = [
                        file
                        for file in existing_files
                        if not report_is_complete(file, args.min_columns)
                    ]

                    if complete_existing_files and not args.overwrite_existing:
                        names = ", ".join(file.name for file in complete_existing_files)
                        print(f"Skipped existing: {names}")
                        clear_failure_records(current_download_dir, station_label, date_text)
                        continue

                    if complete_existing_files and args.overwrite_existing:
                        names = ", ".join(file.name for file in complete_existing_files)
                        print(f"Overwriting existing: {names}")

                    for file in existing_files:
                        if file in incomplete_existing_files:
                            columns = count_report_columns(file)
                            print(
                                f"Re-downloading incomplete file: {file.name} "
                                f"({columns} columns)"
                            )
                        file.unlink(missing_ok=True)

                    try:
                        output_file = download_one_report(
                            page,
                            context,
                            args,
                            station,
                            date_text,
                            output_base,
                            args.wait_seconds,
                            args.report_timeout_seconds,
                            args.min_columns,
                            args.download_retries,
                        )
                        print(f"Downloaded: {output_file.name}")
                        clear_failure_records(current_download_dir, station_label, date_text)
                    except Exception as exc:
                        print(f"Failed: {station_label} - {date_text}")
                        print(exc)
                        skipped_file = append_skipped_day(
                            current_download_dir,
                            station_label,
                            date_text,
                            exc,
                        )
                        print(f"Logged skipped day: {skipped_file}")
                        try:
                            screenshot = save_failure_screenshot(
                                page,
                                current_download_dir,
                                station_label,
                                date_text,
                            )
                            print(f"Saved screenshot: {screenshot}")
                        except Exception as screenshot_exc:
                            print(f"Could not save failure screenshot: {screenshot_exc}")
                        try:
                            reload_report_page(page, context, args)
                            print("Recovered report form after failure.")
                        except Exception as recovery_exc:
                            print(f"Could not recover report form after failure: {recovery_exc}")

        finally:
            browser.close()

    return used_download_dirs


def combine_files(download_dir):
    require_pandas()

    all_files = []
    for extension in SUPPORTED_DOWNLOAD_EXTENSIONS:
        all_files.extend(download_dir.glob(f"*{extension}"))
    all_files = sorted(all_files)
    combined = []

    for file in all_files:
        try:
            if file.suffix.lower() == ".csv":
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file, engine="openpyxl")

            parts = file.stem.split("_")
            report_date = parts[-1]
            station_name = "_".join(parts[:-1])

            df.insert(0, "Station", station_name)
            df.insert(1, "ReportDate", report_date)

            combined.append(df)

        except Exception as exc:
            print(f"Could not read {file.name}: {exc}")

    if combined:
        final_df = pd.concat(combined, ignore_index=True)
        output_file = download_dir / "combined_gacs_reports.xlsx"
        final_df.to_excel(output_file, index=False)
        print(f"Created: {output_file}")
    else:
        print("No files combined.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Download daily GACS reports and combine the Excel files."
    )
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--session-file", type=Path, default=DEFAULT_SESSION_FILE)
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--start-date", type=parse_date, default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", type=parse_date, default=DEFAULT_END_DATE)
    parser.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument(
        "--report-timeout-seconds",
        type=int,
        default=DEFAULT_REPORT_TIMEOUT_SECONDS,
        help="How long to wait for a generated report download link before skipping.",
    )
    parser.add_argument(
        "--min-columns",
        type=int,
        default=DEFAULT_MIN_COLUMNS,
        help="Require downloaded/existing report files to have at least this many columns.",
    )
    parser.add_argument(
        "--download-retries",
        type=int,
        default=DEFAULT_DOWNLOAD_RETRIES,
        help="How many times to retry a report if it is missing or incomplete.",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Download again and replace an existing report file for the same station/date.",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt for manual login; fail if automatic/session login is unavailable.",
    )
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--combine-only", action="store_true")
    parser.add_argument("--skip-combine", action="store_true")
    parser.add_argument(
        "--first-station-only",
        action="store_true",
        help="Download reports for only the first usable station in the dropdown.",
    )
    parser.add_argument(
        "--station-number",
        type=int,
        help="Download reports for one station by 1-based dropdown order.",
    )
    parser.add_argument(
        "--station-name",
        help="Download reports for one station by name, for example TRIPLEBAY.",
    )
    parser.add_argument(
        "--station-folder",
        action="store_true",
        help="Save each selected station in a folder named STATION_gacs_downloads.",
    )
    parser.add_argument(
        "--list-stations",
        action="store_true",
        help="List station dropdown options and exit without downloading.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.download_dir.is_absolute():
        args.download_dir = SCRIPT_DIR / args.download_dir

    if not args.session_file.is_absolute():
        args.session_file = SCRIPT_DIR / args.session_file

    if args.start_date > args.end_date:
        parser.error("--start-date must be on or before --end-date")

    if args.wait_seconds < 0:
        parser.error("--wait-seconds cannot be negative")

    if args.report_timeout_seconds <= 0:
        parser.error("--report-timeout-seconds must be greater than zero")

    if args.min_columns < 0:
        parser.error("--min-columns cannot be negative")

    if args.download_retries <= 0:
        parser.error("--download-retries must be greater than zero")

    station_filters = [
        args.first_station_only,
        args.station_number is not None,
        bool(args.station_name),
    ]
    if sum(station_filters) > 1:
        parser.error(
            "Use only one of --first-station-only, --station-number, or --station-name"
        )

    if args.login_only:
        save_login_session(
            args.base_url,
            args.session_file,
            args.headless,
            interactive=not args.non_interactive,
        )
        return

    if args.combine_only:
        combine_files(args.download_dir)
        return

    combine_dirs = download_reports(args)

    if not args.skip_combine and not args.list_stations:
        for download_dir in combine_dirs or [args.download_dir]:
            combine_files(download_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
