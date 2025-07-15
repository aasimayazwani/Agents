import sqlite3
from pathlib import Path
import pandas as pd

# === File Paths ===
db_path = Path("vehicles.db")

# === Remove existing DB if it exists ===
if db_path.exists():
    print("🗑️ Deleting existing vehicles.db")
    db_path.unlink()

# === CSV file to table mapping ===
csv_files =  {
    "bus_specifications": "bus_specifications.csv",
    "realtime_inservice_dispatch_data": "realtime_inservice_dispatch_data.csv",
    "realtime_inservice_bus_soc_forecast": "realtime_inservice_bus_soc_forecast.csv",
    "candidates_bus_block_end_soc": "candidates_bus_block_end_soc.csv",
    "routes": "routes.csv",
    "trips": "trips.csv",
    "stop_times": "stop_times.csv",
    "stops": "stops.csv",
    "shapes":"shapes.csv",
    "calendar":"calendar.csv",
    "calendar_dates":"calendar_dates.csv",
    "fare_attributes":"fare_attributes.csv",
    "fare_rules":"fare_rules.csv",
    "agency":"agency.csv",
    "feed_info":"feed_info.csv",
    "frequencies":"frequencies.csv",
    "transfers":"transfers.csv",
    "realtime_ev_soc":"realtime_ev_soc.csv"
}

# === Create a new SQLite connection ===
connection = sqlite3.connect(db_path)

try:
    for table_name, file_name in csv_files.items():
        file_path = Path(file_name)

        if not file_path.exists():
            print(f"⚠️  Skipping missing file: {file_name}")
            continue

        print(f"📦 Importing {file_name} → `{table_name}`")
        df = pd.read_csv(file_path, dtype=str, na_values="", keep_default_na=False)

        # Try converting to numeric types when safe
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="ignore", downcast="float")

        df.to_sql(table_name, connection, if_exists="replace", index=False)

    connection.commit()
    print("✅ All tables loaded successfully.")
finally:
    connection.close()
    print("🧠 Database connection closed.")

print("📁 vehicles.db is ready to use.")
