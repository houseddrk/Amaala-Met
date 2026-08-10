import re


COLUMN_RENAMES = {
    "WindSpeed10m": "Wind_Speed_10Meter",
    "WindSpeed_10m": "Wind_Speed_10Meter",
    "Wind_Speed_10m": "Wind_Speed_10Meter",
    "Wind_Speed__10m": "Wind_Speed_10Meter",
    "WindDirection10m": "Wind_Direction_10Meter",
    "WindDirection_10m": "Wind_Direction_10Meter",
    "Wind_Direction_10m": "Wind_Direction_10Meter",
    "Ambient_temperature_2m": "Temperature_2Meter",
    "Relative_Humidity_2m": "Humidity_2Meter",
}

NORMALIZED_COLUMN_RENAMES = {
    re.sub(r"[^a-z0-9]", "", source.lower()): target
    for source, target in COLUMN_RENAMES.items()
}

PREFERRED_COLUMNS = [
    "Station",
    "ReportDate",
    "Time",
    "Barometric_pressure",
    "Heat_Index",
    "Dew_point_temperature",
    "Wet_bulb_temperature",
    "WBGT",
    "Wind_Speed_10Meter",
    "Wind_Direction_10Meter",
    "Temperature_2Meter",
    "Humidity_2Meter",
    "Rain",
]


def canonical_column_name(column):
    if column in COLUMN_RENAMES:
        return COLUMN_RENAMES[column]

    normalized = re.sub(r"[^a-z0-9]", "", str(column).lower())
    return NORMALIZED_COLUMN_RENAMES.get(normalized, column)


def normalize_report_columns(df):
    df = df.rename(columns={column: canonical_column_name(column) for column in df.columns})
    return coalesce_duplicate_columns(df)


def coalesce_duplicate_columns(df):
    duplicate_names = [column for column in df.columns if list(df.columns).count(column) > 1]
    for column in dict.fromkeys(duplicate_names):
        matching = df.loc[:, df.columns == column]
        combined = matching.bfill(axis=1).iloc[:, 0]
        df = df.drop(columns=column)
        df[column] = combined
    return df


def order_columns(df):
    preferred = [column for column in PREFERRED_COLUMNS if column in df.columns]
    remaining = [column for column in df.columns if column not in preferred]
    return df[preferred + remaining]
