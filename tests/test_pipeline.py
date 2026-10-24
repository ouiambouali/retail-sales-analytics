import numpy as np
import pandas as pd
import pytest
import sqlite3

from src.pipeline import (add_basic_columns, add_duplicate_flags, build_tables,
                          read_raw, write_database)


COLUMNS = ["Invoice", "StockCode", "Description", "Quantity",
           "InvoiceDate", "Price", "Customer ID", "Country"]


def make_sample():
    """A made-up 15-row table with one example of each case we handle."""
    uk = "United Kingdom"
    rows = [
        # normal sales, a cancellation and the non-product types
        ("100001", "10001", "RED MUG", 2, "2010-06-01 10:00:00", 3.0, 12345.0, uk),
        ("100001", "10002", "BLUE MUG", 1, "2010-06-01 10:00:00", 4.0, 12345.0, uk),
        ("C100002", "10001", "RED MUG", -1, "2010-06-02 11:00:00", 3.0, 12345.0, uk),
        ("100003", "POST", "POSTAGE", 1, "2010-06-03 12:00:00", 18.0, 12345.0, uk),
        ("100004", "10003", "FOUND", 5, "2010-06-04 09:30:00", 0.0, np.nan, uk),
        ("A100005", "B", "Adjust bad debt", 1, "2010-06-05 14:00:00", -500.0, np.nan, uk),
        ("100006", "gift_0001_20", "Dotcomgiftshop Gift Voucher \u00a320.00", 1,
         "2010-06-06 15:00:00", 20.0, np.nan, uk),
        ("100007", "TEST001", "This is a test product.", 1, "2010-06-07 16:00:00", 5.0, np.nan, uk),
        ("100008", "10004", "GREEN MUG", 1, "2010-06-08 10:15:00", 2.5, np.nan, "Germany"),
        # an invoice recorded twice inside the double-entry window (1-9 Dec 2010)
        ("200001", "10001", "RED MUG", 2, "2010-12-02 09:00:00", 3.0, 11111.0, "France"),
        ("200001", "10002", "BLUE MUG", 1, "2010-12-02 09:00:00", 4.0, 11111.0, "France"),
        ("200001", "10001", "RED MUG", 2, "2010-12-02 09:00:00", 3.0, 11111.0, "France"),
        ("200001", "10002", "BLUE MUG", 1, "2010-12-02 09:00:00", 4.0, 11111.0, "France"),
        # a repeated line outside the window (a genuine repeat, not a double entry)
        ("300001", "10001", "RED MUG", 1, "2011-03-01 10:00:00", 3.0, 22222.0, "Spain"),
        ("300001", "10001", "RED MUG", 1, "2011-03-01 10:00:00", 3.0, 22222.0, "Spain"),
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_read_raw_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_raw(tmp_path / "nope.csv")


def test_read_raw_missing_column(tmp_path):
    path = tmp_path / "bad.csv"
    make_sample().drop(columns=["Price"]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Price"):
        read_raw(path)


def test_read_raw_reads_all_rows(tmp_path):
    path = tmp_path / "ok.csv"
    make_sample().to_csv(path, index=False)
    assert len(read_raw(path)) == 15


def test_row_type_counts():
    df = add_basic_columns(make_sample())
    counts = df["row_type"].value_counts().to_dict()
    assert counts == {"product": 10, "shipping": 1, "zero_price": 1,
                      "adjustment": 1, "voucher": 1, "test": 1}


def test_cancellation_flag():
    df = add_basic_columns(make_sample())
    assert df["is_cancellation"].sum() == 1
    assert df.loc[df["Invoice"] == "C100002", "is_cancellation"].all()


def test_no_rows_removed():
    sample = make_sample()
    assert len(add_basic_columns(sample)) == len(sample)


def test_input_is_not_modified():
    sample = make_sample()
    before = sample.copy()
    add_basic_columns(sample)
    pd.testing.assert_frame_equal(sample, before)

def flagged():
    return add_duplicate_flags(add_basic_columns(make_sample()))


def test_duplicate_counts():
    df = flagged()
    assert df["is_duplicate"].sum() == 3
    assert df["likely_double_entry"].sum() == 2


def test_double_entry_only_in_window():
    df = flagged()
    assert not df.loc[df["Invoice"] == "300001", "likely_double_entry"].any()
    assert df.loc[df["likely_double_entry"], "Invoice"].eq("200001").all()


def test_first_copy_is_kept():
    df = flagged()
    copies = df[df["Invoice"] == "200001"]
    assert copies["likely_double_entry"].sum() == 2
    assert (~copies["likely_double_entry"]).sum() == 2


def test_is_sale_and_net_value():
    df = flagged()
    sales = df[df["is_sale"]]
    assert len(sales) == 8
    assert (sales["Quantity"] * sales["Price"]).sum() == pytest.approx(25.5)


def test_add_duplicate_flags_needs_row_type():
    with pytest.raises(ValueError, match="row_type"):
        add_duplicate_flags(make_sample())


def test_table_sizes_and_keys():
    invoices, products, lines = build_tables(flagged())
    assert (len(invoices), len(products), len(lines)) == (10, 8, 15)
    assert products["appears_in_sales"].sum() == 3
    assert products["stock_code"].is_unique and invoices["invoice_no"].is_unique


def test_product_description_is_chosen():
    _, products, _ = build_tables(flagged())
    row = products[products["stock_code"] == "10001"].iloc[0]
    assert row["description"] == "RED MUG"


def test_write_database(tmp_path):
    invoices, products, lines = build_tables(flagged())
    db = write_database(invoices, products, lines, tmp_path / "test.db")
    con = sqlite3.connect(db)
    try:
        counts = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("invoices", "products", "invoice_lines")]
        net = con.execute("SELECT SUM(quantity * price) FROM invoice_lines "
                          "WHERE is_sale = 1").fetchone()[0]
        violations = con.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        con.close()
    assert counts == [10, 8, 15]
    assert net == pytest.approx(25.5)
    assert violations == []