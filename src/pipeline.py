from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

EXPECTED_COLUMNS = ["Invoice", "StockCode", "Description", "Quantity",
                    "InvoiceDate", "Price", "Customer ID", "Country"]

# Invoices first recorded in this window were entered twice (see notebook notes).
DOUBLE_ENTRY_START = "2010-12-01"
DOUBLE_ENTRY_END = "2010-12-10"  # exclusive: the window is 1-9 December 2010

SCHEMA = """
CREATE TABLE invoices (
    invoice_no      TEXT PRIMARY KEY,
    invoice_date    TEXT NOT NULL,
    customer_id     TEXT,
    country         TEXT NOT NULL,
    is_cancellation INTEGER NOT NULL
);
CREATE TABLE products (
    stock_code       TEXT PRIMARY KEY,
    description      TEXT,
    appears_in_sales INTEGER NOT NULL
);
CREATE TABLE invoice_lines (
    line_id             INTEGER PRIMARY KEY,
    invoice_no          TEXT NOT NULL REFERENCES invoices(invoice_no),
    stock_code          TEXT NOT NULL REFERENCES products(stock_code),
    quantity            INTEGER NOT NULL,
    price               REAL NOT NULL,
    row_type            TEXT NOT NULL,
    is_duplicate        INTEGER NOT NULL,
    likely_double_entry INTEGER NOT NULL,
    is_sale             INTEGER NOT NULL
);
"""

def read_raw(csv_path):
    """Read the raw CSV and check that the expected columns exist."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Raw file not found: {csv_path}")

    df = pd.read_csv(csv_path, dtype={"Invoice": str, "StockCode": str})

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {csv_path.name}: {missing}")
    return df

def add_basic_columns(df):
    """Add date, customer, cancellation and row_type columns (no rows are removed)."""
    df = df.copy()

    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["customer_id"] = df["Customer ID"].astype("Int64").astype("string")
    df["has_customer"] = df["Customer ID"].notna()
    df["is_cancellation"] = df["Invoice"].str.startswith("C")

    code = df["StockCode"].str.strip().str.upper()
    desc = df["Description"].str.strip()

    conditions = [
        df["Price"] < 0,
        df["Price"] == 0,
        code.isin(["POST", "DOT", "C2"]) | (desc == "Next Day Carriage"),
        code.isin(["BANK CHARGES", "AMAZONFEE", "CRUK"]),
        code.isin(["M", "ADJUST", "ADJUST2", "B"]),
        code == "D",
        code == "S",
        code.str.startswith("GIFT") | desc.str.startswith("Dotcomgiftshop Gift Voucher", na=False),
        code.str.startswith("TEST"),
        code == "C3",
    ]
    labels = ["adjustment", "zero_price", "shipping", "fee", "adjustment",
              "discount", "sample", "voucher", "test", "other"]

    df["row_type"] = np.select(conditions, labels, default="product")
    return df

def add_duplicate_flags(df):
    """Add is_duplicate, likely_double_entry and is_sale (no rows are removed)."""
    if "row_type" not in df.columns:
        raise ValueError("Run add_basic_columns first: 'row_type' is missing.")
    df = df.copy()

    df["is_duplicate"] = df.duplicated(subset=EXPECTED_COLUMNS, keep="first")

    invoice_start = df.groupby("Invoice")["InvoiceDate"].transform("min")
    in_window = (invoice_start >= DOUBLE_ENTRY_START) & (invoice_start < DOUBLE_ENTRY_END)

    groups = df.groupby(EXPECTED_COLUMNS, dropna=False)
    group_size = groups["Invoice"].transform("size")
    position = groups.cumcount()
    df["likely_double_entry"] = in_window & (position >= group_size / 2)

    df["is_sale"] = (df["row_type"] == "product") & ~df["likely_double_entry"]
    return df

def _pick_descriptions(codes, descriptions):
    """One description per code: most common, ties go to the first alphabetically."""
    pairs = pd.DataFrame({"stock_code": codes, "description": descriptions})
    pairs = pairs.dropna(subset=["description"])
    counts = (pairs.groupby(["stock_code", "description"]).size()
                   .rename("n").reset_index())
    counts = counts.sort_values(["stock_code", "n", "description"],
                                ascending=[True, False, True])
    return counts.drop_duplicates("stock_code", keep="first")[["stock_code", "description"]]


def build_tables(df):
    """Build the invoices, products and lines tables from the flagged data."""
    needed = ["row_type", "is_sale", "is_cancellation", "customer_id",
              "is_duplicate", "likely_double_entry"]
    absent = [c for c in needed if c not in df.columns]
    if absent:
        raise ValueError(f"Run the earlier steps first, missing columns: {absent}")

    df = df.copy()
    df["stock_code"] = df["StockCode"].str.strip().str.upper()
    df["description_clean"] = df["Description"].str.strip().str.upper()

    sold = df[df["is_sale"]]
    products_sold = _pick_descriptions(sold["stock_code"], sold["description_clean"])
    products_sold["appears_in_sales"] = True

    rest = df[~df["stock_code"].isin(products_sold["stock_code"])]
    products_rest = _pick_descriptions(rest["stock_code"], rest["description_clean"])
    no_desc = sorted(set(rest["stock_code"]) - set(products_rest["stock_code"]))
    no_desc = pd.DataFrame({"stock_code": no_desc, "description": pd.NA})
    products_rest = pd.concat([products_rest, no_desc], ignore_index=True)
    products_rest["appears_in_sales"] = False

    products = pd.concat([products_sold, products_rest], ignore_index=True)

    invoices = (df.groupby("Invoice")
                  .agg(invoice_date=("InvoiceDate", "min"),
                       customer_id=("customer_id", "first"),
                       country=("Country", "first"),
                       is_cancellation=("is_cancellation", "first"))
                  .reset_index()
                  .rename(columns={"Invoice": "invoice_no"}))

    lines = pd.DataFrame({
        "line_id": np.arange(1, len(df) + 1),
        "invoice_no": df["Invoice"].to_numpy(),
        "stock_code": df["stock_code"].to_numpy(),
        "quantity": df["Quantity"].to_numpy(),
        "price": df["Price"].to_numpy(),
        "row_type": df["row_type"].to_numpy(),
        "is_duplicate": df["is_duplicate"].to_numpy(),
        "likely_double_entry": df["likely_double_entry"].to_numpy(),
        "is_sale": df["is_sale"].to_numpy(),
    })

    if not products["stock_code"].is_unique:
        raise ValueError("products has a duplicated stock_code")
    if not invoices["invoice_no"].is_unique:
        raise ValueError("invoices has a duplicated invoice_no")
    if (~lines["invoice_no"].isin(invoices["invoice_no"])).any():
        raise ValueError("A line points to an unknown invoice")
    if (~lines["stock_code"].isin(products["stock_code"])).any():
        raise ValueError("A line points to an unknown product")

    return invoices, products, lines

def write_database(invoices, products, lines, db_path):
    """Create the SQLite database from the three tables."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    inv = invoices.copy()
    inv["invoice_date"] = inv["invoice_date"].dt.strftime("%Y-%m-%d %H:%M:%S")
    inv["is_cancellation"] = inv["is_cancellation"].astype(int)
    inv["customer_id"] = inv["customer_id"].astype(object).where(inv["customer_id"].notna(), None)

    prod = products.copy()
    prod["appears_in_sales"] = prod["appears_in_sales"].astype(int)
    prod["description"] = prod["description"].astype(object).where(prod["description"].notna(), None)

    ln = lines.copy()
    for c in ["is_duplicate", "likely_double_entry", "is_sale"]:
        ln[c] = ln[c].astype(int)

    con = sqlite3.connect(tmp_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        inv.to_sql("invoices", con, if_exists="append", index=False, chunksize=50000)
        prod.to_sql("products", con, if_exists="append", index=False, chunksize=50000)
        ln.to_sql("invoice_lines", con, if_exists="append", index=False, chunksize=50000)
        con.commit()
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key violations found in the new database")
    finally:
        con.close()

    tmp_path.replace(db_path)
    return db_path

RAW_PATH = Path("data/online_retail_II.csv")
DB_PATH = Path("data/processed/retail.db")


def run(raw_path=RAW_PATH, db_path=DB_PATH):
    """Run the whole pipeline: read, classify, flag, build tables, write the database."""
    print(f"Reading {raw_path} ...")
    df = read_raw(raw_path)
    print(f"  {len(df):,} rows read")

    df = add_basic_columns(df)
    df = add_duplicate_flags(df)
    print(f"  {int(df['is_duplicate'].sum()):,} duplicate rows, "
          f"{int(df['likely_double_entry'].sum()):,} likely double entries")

    invoices, products, lines = build_tables(df)
    print(f"  {len(invoices):,} invoices, {len(products):,} products, {len(lines):,} lines")

    write_database(invoices, products, lines, db_path)
    print(f"Database written to {db_path}")
    return db_path


if __name__ == "__main__":
    import sys

    try:
        run()
    except (FileNotFoundError, ValueError) as err:
        print(f"Pipeline stopped: {err}")
        sys.exit(1)