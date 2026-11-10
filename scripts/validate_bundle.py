"""Fast pre-deployment validation for RUBY source files and bundled data."""
import csv
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
with (ROOT/"data"/"city_pincodes.csv").open(newline="",encoding="utf-8") as f:
    pins=list(csv.DictReader(f))
with (ROOT/"data"/"products.csv").open(newline="",encoding="utf-8") as f:
    products=list(csv.DictReader(f))
counts=Counter(r["city"] for r in pins)
assert len(counts)==28 and len(pins)==280 and set(counts.values())=={10}
assert len({r["pincode"] for r in pins})==280
assert all(len(r["pincode"])==6 and r["pincode"].isdigit() for r in pins)
assert len(products)==24 and len({r["sku"] for r in products})==24
for p in products:
    assert (ROOT/"assets"/"products"/p["image"]).is_file()
print("RUBY bundle validation passed")
print(f"Cities: {len(counts)} | PIN candidates: {len(pins)} | Products: {len(products)}")
