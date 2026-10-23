"""
Load every APPROVED row from data/staging/ into the main dataset.

    python3 src/ingest.py                 # load all approved rows
    python3 src/ingest.py --accept X00003 # accept the NEW value of a flagged conflict

Reads every CSV in data/staging/ (not the templates folder):
  * capacity files - have a `capacity_value` column
  * BOM files      - have a `material_name` column
Only rows with Y in `approve` are loaded. Running it twice adds nothing the
second time. If a new document disagrees with an existing capacity for the same
plant + product + basis, the old value is kept and the clash is written to
conflicts.csv for you to decide.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import (CAPACITY_BASIS, PRODUCT_CATEGORIES, QUANTITY_TYPES, STAGING,  # noqa: E402
                    add_row, load, name_key, save, to_tpa, today)

CONFIDENCE_BY_BASIS = {
    "EC approved": "Verified", "Consent to operate": "Verified",
    "EC proposed": "Partially verified", "Installed (company)": "Partially verified",
    "PLI committed": "Partially verified",
}


class DB:
    def __init__(self):
        self.t = {n: load(n) for n in ["companies", "plants", "products", "plant_products",
                                        "materials", "bom", "evidence", "conflicts"]}
        self.added = {n: 0 for n in self.t}
        self.problems: list[str] = []

    def add(self, table, row):
        self.t[table], new_id = add_row(self.t[table], table, row)
        self.added[table] += 1
        return new_id

    def save(self):
        for n, df in self.t.items():
            save(n, df)

    # ---- lookups that create the record when it does not exist yet ----
    def company(self, name):
        k = name_key(name)
        df = self.t["companies"]
        hit = df[df.name_key == k]
        return hit.company_id.iloc[0] if len(hit) else self.add("companies", {"company_name": name.strip(), "name_key": k})

    def plant(self, cid, address, state, company_name):
        df = self.t["plants"]
        mine = df[df.company_id == cid]
        if address.strip():
            pk = f"{cid}|{name_key(address)}"
            hit = mine[mine.plant_key == pk]
            if len(hit):
                return hit.plant_id.iloc[0]
            # same company, address that contains / is contained in an existing one
            ak = name_key(address)
            loose = mine[mine.plant_key.str.split("|").str[1].apply(lambda x: bool(x) and (x in ak or ak in x))]
            if len(loose) == 1:
                return loose.plant_id.iloc[0]
            return self.add("plants", {"company_id": cid, "plant_name": company_name, "address": address,
                                       "state": state, "plant_key": pk, "manufacturing_status": "Product evidence"})
        if len(mine) == 1:
            return mine.plant_id.iloc[0]
        pk = f"{cid}|unspecified"
        hit = mine[mine.plant_key == pk]
        if len(hit):
            return hit.plant_id.iloc[0]
        return self.add("plants", {"company_id": cid, "plant_name": f"{company_name} (site not stated)",
                                   "address": "Not stated in source", "state": state, "plant_key": pk,
                                   "manufacturing_status": "Product evidence"})

    def product(self, name, category):
        k = name_key(name)
        df = self.t["products"]
        hit = df[df.name_key.str.replace(" ", "") == k.replace(" ", "")]   # 'para amino phenol' == 'para-aminophenol'
        if len(hit):
            return hit.product_id.iloc[0]
        cat = category if category in PRODUCT_CATEGORIES else "API"
        return self.add("products", {"product_name": name.strip(), "category": cat, "name_key": k})

    def material(self, name, category):
        k = name_key(name)
        df = self.t["materials"]
        hit = df[df.name_key.str.replace(" ", "") == k.replace(" ", "")]
        return hit.material_id.iloc[0] if len(hit) else self.add(
            "materials", {"material_name": name.strip(), "material_category": category or "Raw material", "name_key": k})

    def evidence(self, etype, eid, r, claim, confidence):
        ev = self.t["evidence"]
        if len(ev[(ev.entity_id == eid) & (ev.source_id == r.source_id)]):
            return
        self.add("evidence", {"entity_type": etype, "entity_id": eid, "source_id": r.source_id,
                              "page": r.get("page", ""), "claim": claim, "raw_text": str(r.get("raw_text", ""))[:500],
                              "confidence": confidence, "extracted_on": today()})


def ingest_capacity(db: DB, df: pd.DataFrame, fname: str):
    for i, r in df.iterrows():
        where = f"{fname} row {i + 2}"
        if not r.company_name.strip() or not r.product_name.strip():
            db.problems.append(f"{where}: company_name and product_name are required"); continue
        if r.capacity_basis not in CAPACITY_BASIS:
            db.problems.append(f"{where}: capacity_basis must be one of {CAPACITY_BASIS}"); continue
        tpa = r.get("capacity_tpa", "") or to_tpa(r.capacity_value, r.capacity_unit)
        if r.capacity_value and tpa in (None, ""):
            db.problems.append(f"{where}: unknown unit '{r.capacity_unit}' - fill capacity_tpa yourself"); continue
        cid = db.company(r.company_name)
        pid = db.plant(cid, r.get("plant_address", ""), r.get("state", ""), r.company_name.strip())
        prid = db.product(r.product_name, r.get("product_category", "API"))
        pp = db.t["plant_products"]
        same = pp[(pp.plant_id == pid) & (pp.product_id == prid) & (pp.capacity_basis == r.capacity_basis)]
        if len(same[same.source_id == r.source_id]):
            continue                                            # already loaded
        if len(same):
            old = same.iloc[-1]
            if str(old.capacity_tpa) != str(tpa):
                cf = db.t["conflicts"]
                if not len(cf[(cf.record_id == old.pp_id) & (cf.new_source_id == r.source_id)]):
                    db.add("conflicts", {"table": "plant_products", "record_id": old.pp_id, "field": "capacity_tpa",
                                         "old_value": old.capacity_tpa, "new_value": tpa,
                                         "old_source_id": old.source_id, "new_source_id": r.source_id,
                                         "flagged_on": today(), "resolution": "open"})
                continue
        conf = r.get("confidence", "") or CONFIDENCE_BY_BASIS[r.capacity_basis]
        ppid = db.add("plant_products", {
            "plant_id": pid, "product_id": prid, "capacity_value": r.capacity_value, "capacity_unit": r.capacity_unit,
            "capacity_tpa": tpa, "capacity_basis": r.capacity_basis,
            "actual_output_tpa": r.get("actual_output_tpa", ""), "evidence_status": conf,
            "source_id": r.source_id, "page": r.get("page", ""),
        })
        db.evidence("plant_product", ppid, r,
                    f"{r.product_name}: {r.capacity_value} {r.capacity_unit} ({r.capacity_basis})", conf)


def ingest_bom(db: DB, df: pd.DataFrame, fname: str):
    for i, r in df.iterrows():
        where = f"{fname} row {i + 2}"
        if not r.product_name.strip() or not r.material_name.strip():
            db.problems.append(f"{where}: product_name and material_name are required"); continue
        qt = r.quantity_type if r.quantity_type in QUANTITY_TYPES else "Unknown"
        prid = db.product(r.product_name, r.get("product_category", "API"))
        mid = db.material(r.material_name, r.get("material_category", "Raw material"))
        plant_id = ""
        if r.get("company_name", "").strip() and r.get("plant_address", "").strip():
            cid = db.company(r.company_name)
            plant_id = db.plant(cid, r.plant_address, r.get("state", ""), r.company_name.strip())
        b = db.t["bom"]
        if len(b[(b.product_id == prid) & (b.material_id == mid) & (b.plant_id == plant_id) & (b.source_id == r.source_id)]):
            continue
        bid = db.add("bom", {"product_id": prid, "material_id": mid, "plant_id": plant_id,
                             "quantity_value": r.quantity_value, "quantity_unit": r.quantity_unit,
                             "kg_per_kg": r.get("kg_per_kg", ""), "quantity_type": qt,
                             "source_id": r.source_id, "page": r.get("page", "")})
        conf = {"Reported": "Verified", "Calculated": "Partially verified"}.get(qt, "Estimated")
        db.evidence("bom", bid, r, f"{r.material_name} for {r.product_name}: {r.quantity_value} {r.quantity_unit}", conf)


def accept(conflict_id: str):
    db = DB()
    cf, pp = db.t["conflicts"], db.t["plant_products"]
    c = cf[cf.conflict_id == conflict_id]
    if c.empty:
        sys.exit(f"No conflict {conflict_id}")
    c = c.iloc[0]
    i = pp.index[pp.pp_id == c.record_id][0]
    pp.loc[i, "capacity_tpa"] = c.new_value
    pp.loc[i, "source_id"] = c.new_source_id
    cf.loc[cf.conflict_id == conflict_id, "resolution"] = f"accepted new value on {today()}"
    db.save()
    print(f"{c.record_id}: capacity_tpa {c.old_value} -> {c.new_value} (old evidence kept)")


def main():
    db = DB()
    files = sorted(p for p in STAGING.glob("*.csv"))
    for f in files:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        if "approve" not in df.columns or "source_id" not in df.columns:
            continue
        df = df[df.approve.str.strip().str.upper() == "Y"].reset_index(drop=True)
        if df.empty:
            continue
        if "capacity_value" in df.columns:
            ingest_capacity(db, df, f.name)
        elif "material_name" in df.columns:
            ingest_bom(db, df, f.name)
    db.save()
    print("Added:", {k: v for k, v in db.added.items() if k != "conflicts"})
    from link_products import build
    links = build()
    print(f"Product links rebuilt: {len(links)} (intermediates/KSMs -> APIs)")
    if db.added["conflicts"]:
        print(f"Conflicts flagged: {db.added['conflicts']} (see data/processed/conflicts.csv; "
              "accept with: python3 src/ingest.py --accept <conflict_id>)")
    for p in db.problems:
        print("SKIPPED:", p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept")
    a = ap.parse_args()
    accept(a.accept) if a.accept else main()
