import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_city_pin_coverage_is_28_by_10():
    with (ROOT / "data" / "city_pincodes.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    counts = Counter(r["city"] for r in rows)
    assert len(counts) == 28
    assert len(rows) == 280
    assert set(counts.values()) == {10}
    assert len({r["pincode"] for r in rows}) == 280
    assert all(len(r["pincode"]) == 6 and r["pincode"].isdigit() for r in rows)


def test_catalogue_rows_and_images():
    with (ROOT / "data" / "products.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 24
    assert len({r["sku"] for r in rows}) == 24
    for row in rows:
        assert (ROOT / "assets" / "products" / row["image"]).is_file()
        assert float(row["mrp"]) > 0
        assert float(row["cost"]) > 0


def test_core_password_hashing():
    from core.security import hash_password, verify_password
    value = hash_password("ValidRubyPass#2026")
    assert verify_password("ValidRubyPass#2026", value)
    assert not verify_password("wrong-password", value)
