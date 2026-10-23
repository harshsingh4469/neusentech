"""
Read a CDSCO "WHO-GMP certified manufacturing units" PDF and load every
company + plant (manufacturing unit) into the dataset.

    python3 src/extract_who_gmp.py data/raw/who_gmp/<file>.pdf

The PDF must already be registered in sources.csv (src/download.py does that).
What this proves: the unit holds WHO-GMP / CoPP certification on the list date.
What it does NOT prove: that the unit makes any particular API. Product evidence
comes later from EC documents, PLI lists and company reports.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import ROOT, add_row, load, name_key, save, today  # noqa: E402
from download import sha256  # noqa: E402

STATES = [
    "Andaman & Nicobar", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
    "Chhattisgarh", "Dadra & Nagar Haveli", "Daman & Diu", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu & Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh",
    "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Orissa", "Puducherry", "Pondicherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "Uttrakhand", "West Bengal",
]
STATE_KEYS = {name_key(s): s for s in STATES}


def clean(c) -> str:
    return re.sub(r"\s+", " ", str(c or "")).strip()


def as_state(text: str) -> str | None:
    k = name_key(re.sub(r"(?i)island|state|ut\b", "", text))
    for sk, s in STATE_KEYS.items():
        if k == sk or (k.startswith(sk) and len(k) - len(sk) < 4):
            return {"Orissa": "Odisha", "Pondicherry": "Puducherry", "Uttrakhand": "Uttarakhand"}.get(s, s)
    return None


def find_columns(row: list[str]) -> dict | None:
    low = [re.sub(r"\s+", "", c.lower()) for c in row]
    firm = next((i for i, c in enumerate(low) if "firm" in c), None)
    addr = next((i for i, c in enumerate(low) if "address" in c), None)
    if firm is None or addr is None:
        return None
    cat = next((i for i, c in enumerate(low) if "category" in c), None)
    return {"firm": firm, "addr": addr, "cat": cat}


def parse(pdf_path: Path) -> list[dict]:
    records, cols, state = [], None, ""
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for raw in table:
                    row = [clean(c) for c in raw]
                    filled = [c for c in row if c]
                    if not filled:
                        continue
                    hdr = find_columns(row)
                    if hdr:
                        cols = hdr
                        continue
                    # a row that only names a state starts a new state block
                    if len(filled) <= 2 and as_state(filled[-1]):
                        state = as_state(filled[-1])
                        continue
                    if cols is None or max(v for v in cols.values() if v is not None) >= len(row):
                        continue
                    firm, addr = row[cols["firm"]], row[cols["addr"]]
                    cat = row[cols["cat"]] if cols["cat"] is not None and cols["cat"] < len(row) else ""
                    serial = next((c for c in row[:cols["firm"]] if c), "")
                    if not firm and records and not serial:          # continuation line
                        records[-1]["address"] = clean(records[-1]["address"] + " " + addr)
                        records[-1]["categories"] = clean(records[-1]["categories"] + " " + cat)
                        continue
                    if not firm or firm.lower() in ("nil", "-"):
                        continue
                    records.append({"firm": firm, "address": addr, "categories": cat,
                                    "state": state or (as_state(addr.split(",")[-1]) or ""),
                                    "page": pno})
    return records


def main(pdf_path: Path) -> None:
    sources = load("sources")
    digest = sha256(pdf_path)
    src = sources[sources.sha256 == digest]
    if src.empty:
        sys.exit("Register the PDF first:  python3 src/download.py --register <file> --type who_gmp ...")
    sid = src.source_id.iloc[0]

    recs = parse(pdf_path)
    print(f"Rows read from PDF: {len(recs)}")
    companies, plants, evidence = load("companies"), load("plants"), load("evidence")
    comp_by_key = dict(zip(companies.name_key, companies.company_id))
    plant_keys = set(plants.plant_key)
    ev_keys = set(zip(evidence.entity_id, evidence.source_id))
    added = {"companies": 0, "plants": 0, "evidence": 0}

    for r in recs:
        firm = re.sub(r"(?i)^m\s*/\s*s\.?\s*", "", r["firm"]).strip(" ,")
        ck = name_key(firm)
        if ck not in comp_by_key:
            companies, cid = add_row(companies, "companies", {"company_name": firm, "name_key": ck})
            comp_by_key[ck] = cid
            added["companies"] += 1
        cid = comp_by_key[ck]
        pk = f"{cid}|{name_key(r['address'])}"
        if pk not in plant_keys:
            plants, pid = add_row(plants, "plants", {
                "company_id": cid, "plant_name": firm, "address": r["address"], "state": r["state"],
                "plant_key": pk, "who_gmp_categories": r["categories"],
                "manufacturing_status": "WHO-GMP certified (list date)",
            })
            plant_keys.add(pk)
            added["plants"] += 1
        else:
            pid = plants.loc[plants.plant_key == pk, "plant_id"].iloc[0]
        if (pid, sid) not in ev_keys:
            evidence, _ = add_row(evidence, "evidence", {
                "entity_type": "plant", "entity_id": pid, "source_id": sid, "page": r["page"],
                "claim": "Unit listed as WHO-GMP / CoPP certified",
                "raw_text": f"{r['firm']} | {r['address']} | {r['categories']}"[:500],
                "confidence": "Verified", "extracted_on": today(),
            })
            ev_keys.add((pid, sid))
            added["evidence"] += 1

    save("companies", companies); save("plants", plants); save("evidence", evidence)
    print(f"Added: {added}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
