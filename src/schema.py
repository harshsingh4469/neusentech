"""
NeusenTech - shared table definitions and helpers.

Every table is a CSV file in data/processed/. CSV keeps the project simple:
you can open any table in Excel / Google Sheets, and pandas reads it in one line.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
STAGING = DATA / "staging"
PROCESSED = DATA / "processed"

# table name -> (id column, id prefix, columns)
TABLES = {
    "sources": ("source_id", "S", [
        "source_id", "title", "publisher", "source_type", "url",
        "document_date", "local_file", "sha256", "downloaded_on", "status",
    ]),
    "companies": ("company_id", "C", [
        "company_id", "company_name", "name_key", "official_website",
    ]),
    "plants": ("plant_id", "P", [
        "plant_id", "company_id", "plant_name", "address", "state",
        "plant_key", "who_gmp_categories", "manufacturing_status",
    ]),
    "products": ("product_id", "PR", [
        "product_id", "product_name", "category", "name_key",
    ]),
    "plant_products": ("pp_id", "PP", [
        "pp_id", "plant_id", "product_id",
        "capacity_value", "capacity_unit", "capacity_tpa",
        "capacity_basis",          # see CAPACITY_BASIS below
        "actual_output_tpa",       # only when a source reports real production
        "evidence_status", "source_id", "page",
    ]),
    "materials": ("material_id", "RM", [
        "material_id", "material_name", "material_category", "name_key",
    ]),
    "bom": ("bom_id", "B", [
        "bom_id", "product_id", "material_id", "plant_id",
        "quantity_value", "quantity_unit", "kg_per_kg",
        "quantity_type",           # see QUANTITY_TYPES below
        "source_id", "page",
    ]),
    "evidence": ("evidence_id", "E", [
        "evidence_id", "entity_type", "entity_id", "source_id", "page",
        "claim", "raw_text", "confidence", "extracted_on",
    ]),
    "product_links": ("link_id", "L", [
        "link_id", "from_product_id", "to_product_id", "to_product_name",
        "relation",               # 'intermediate of' | 'raw material of'
        "method",                 # 'name rule' | 'BOM' | 'manual'
        "source_id", "note",
    ]),
    "leads": ("lead_id", "LD", [
        "lead_id", "title", "url", "found_on", "query", "source_type", "publisher",
        "discovered_on", "status", "note",
    ]),
    "conflicts": ("conflict_id", "X", [
        "conflict_id", "table", "record_id", "field", "old_value",
        "new_value", "old_source_id", "new_source_id", "flagged_on", "resolution",
    ]),
}

PRODUCT_CATEGORIES = ["API", "Intermediate", "KSM", "Formulation"]

CAPACITY_BASIS = [
    "EC approved",          # environmental clearance granted
    "EC proposed",          # in an application / EIA, not yet granted
    "Consent to operate",   # pollution-control-board consent order
    "Installed (company)",  # company annual report / website / DRHP
    "PLI committed",        # Department of Pharmaceuticals PLI approval
]

QUANTITY_TYPES = ["Reported", "Calculated", "Engineering estimate", "Unknown"]

CONFIDENCE = ["Verified", "Partially verified", "Estimated", "Requires validation"]


def today() -> str:
    return date.today().isoformat()


def name_key(text: str) -> str:
    """Normalise a name so 'M/s. Granules India Ltd.' == 'Granules India Limited'."""
    t = str(text or "").lower()
    t = re.sub(r"^\s*m\s*/\s*s\.?\s*", "", t)
    t = t.replace("&", " and ")
    t = re.sub(r"\b(private|pvt)\b", "pvt", t)
    t = re.sub(r"\b(limited|ltd)\b", "ltd", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def load(table: str) -> pd.DataFrame:
    cols = TABLES[table][2]
    path = PROCESSED / f"{table}.csv"
    if path.exists():
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    return pd.DataFrame(columns=cols, dtype=str)


def save(table: str, df: pd.DataFrame) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df[TABLES[table][2]].to_csv(PROCESSED / f"{table}.csv", index=False)


def next_id(df: pd.DataFrame, table: str) -> str:
    id_col, prefix, _ = TABLES[table]
    nums = df[id_col].str.replace(prefix, "", regex=False)
    nums = pd.to_numeric(nums, errors="coerce").dropna()
    n = int(nums.max()) + 1 if len(nums) else 1
    return f"{prefix}{n:05d}"


def add_row(df: pd.DataFrame, table: str, row: dict) -> tuple[pd.DataFrame, str]:
    id_col = TABLES[table][0]
    new_id = next_id(df, table)
    row = {c: "" for c in TABLES[table][2]} | {k: ("" if v is None else str(v)) for k, v in row.items()}
    row[id_col] = new_id
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True), new_id


# ---------- units -----------------------------------------------------------
# Factor that converts a quantity in this unit into TONNES PER YEAR.
UNIT_TO_TPA = {
    "tpa": 1, "mt/year": 1, "mtpa": 1, "t/year": 1, "tonnes/year": 1, "mt/annum": 1, "tpy": 1,
    "tpm": 12, "mt/month": 12, "mt/m": 12, "t/month": 12, "tonnes/month": 12, "mtpm": 12,
    "kg/month": 12 / 1000, "kgpm": 12 / 1000, "kg/m": 12 / 1000,
    "kg/day": 330 / 1000, "kgpd": 330 / 1000,   # 330 working days is a stated assumption
    "tpd": 330, "mt/day": 330,
    "kg/year": 1 / 1000, "kg/annum": 1 / 1000, "kgpa": 1 / 1000,
}


def clean_unit(unit: str) -> str:
    u = str(unit or "").lower().strip()
    u = u.replace(" ", "").replace("per", "/").replace("tons", "mt").replace("tonnes", "mt")
    u = u.replace("annum", "year").replace("yr", "year").replace("mtyear", "mt/year")
    aliases = {"mt/yearear": "mt/year", "t/a": "tpa", "mt/a": "tpa", "mtpm": "mt/month",
               "kg/mon": "kg/month", "mt/mon": "mt/month", "mt/mth": "mt/month"}
    return aliases.get(u, u)


def to_tpa(value, unit) -> float | None:
    """Convert a capacity to tonnes/year. Returns None if the unit is unknown."""
    try:
        v = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    u = clean_unit(unit)
    if u in UNIT_TO_TPA:
        return round(v * UNIT_TO_TPA[u], 4)
    if u.replace("mt", "t") in UNIT_TO_TPA:
        return round(v * UNIT_TO_TPA[u.replace("mt", "t")], 4)
    return None
