"""
Raw-material demand:   D_m = sum over plant-products i of  Q_i x r_(i,m)

  Q_i   = annual output of plant-product i in tonnes (actual output if reported,
          otherwise the best available capacity - see BASIS_PRIORITY)
  r_i,m = kg of material m per kg of product (plant-specific factor first,
          otherwise a product-level factor)

Missing Q or r is NEVER treated as zero: those rows are kept and counted as
"insufficient data" so the coverage is visible.

    python3 src/demand.py      -> writes data/processed/demand_detail.csv and demand_summary.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import PROCESSED, load  # noqa: E402

# when one plant-product has several capacity figures, use ONE of them, in this order
BASIS_PRIORITY = ["Actual output", "Consent to operate", "Installed (company)",
                  "EC approved", "PLI committed", "EC proposed"]
FACTOR_PRIORITY = {"Reported": 0, "Calculated": 1, "Engineering estimate": 2}


def num(s):
    return pd.to_numeric(s, errors="coerce")


def best_output(pp: pd.DataFrame) -> pd.DataFrame:
    """One row per plant+product with the single best Q and its label (avoids double counting)."""
    if pp.empty:
        return pp.assign(Q=[], Q_basis=[])
    pp = pp.copy()
    act = num(pp.actual_output_tpa)
    pp["Q"] = act.where(act.notna(), num(pp.capacity_tpa))
    pp["Q_basis"] = pp.capacity_basis.where(act.isna(), "Actual output")
    pp["rank"] = pp.Q_basis.map({b: i for i, b in enumerate(BASIS_PRIORITY)}).fillna(99)
    pp = pp.sort_values(["rank"]).drop_duplicates(["plant_id", "product_id"])
    return pp.drop(columns="rank")


def best_factor(bom: pd.DataFrame) -> pd.DataFrame:
    """One factor per (product, material, plant_id or '') - best quantity_type, then average."""
    b = bom.copy()
    b["r"] = num(b.kg_per_kg)
    b = b[b.r.notna() & b.quantity_type.isin(FACTOR_PRIORITY)]
    if b.empty:
        return b
    b["rank"] = b.quantity_type.map(FACTOR_PRIORITY)
    b = b[b["rank"] == b.groupby(["product_id", "material_id", "plant_id"])["rank"].transform("min")]
    return (b.groupby(["product_id", "material_id", "plant_id"], as_index=False)
             .agg(r=("r", "mean"), quantity_type=("quantity_type", "first"),
                  factor_sources=("source_id", lambda s: ", ".join(sorted(set(s))))))


def demand_detail() -> pd.DataFrame:
    pp, bom = load("plant_products"), load("bom")
    out_cols = ["material_id", "product_id", "plant_id", "Q", "Q_basis", "r", "quantity_type",
                "factor_level", "factor_sources", "demand_tpa", "status"]
    if pp.empty or bom.empty:
        return pd.DataFrame(columns=out_cols)
    q = best_output(pp)
    f = best_factor(bom)
    pairs = bom[["product_id", "material_id"]].drop_duplicates()   # every documented input, even with no factor
    rows = []
    for _, x in q.merge(pairs, on="product_id").iterrows():
        plant_f = f[(f.product_id == x.product_id) & (f.material_id == x.material_id) & (f.plant_id == x.plant_id)]
        gen_f = f[(f.product_id == x.product_id) & (f.material_id == x.material_id) & (f.plant_id == "")]
        use, level = (plant_f, "Plant-specific") if len(plant_f) else (gen_f, "Product-level") if len(gen_f) else (None, "")
        r = use.r.iloc[0] if use is not None else None
        Q = x.Q if pd.notna(x.Q) else None
        rows.append({
            "material_id": x.material_id, "product_id": x.product_id, "plant_id": x.plant_id,
            "Q": Q, "Q_basis": x.Q_basis, "r": r,
            "quantity_type": use.quantity_type.iloc[0] if use is not None else "Unknown",
            "factor_level": level, "factor_sources": use.factor_sources.iloc[0] if use is not None else "",
            "demand_tpa": round(Q * r, 3) if Q is not None and r is not None else None,
            "status": "Calculated" if Q is not None and r is not None else
                      ("No consumption factor" if Q is not None else "No output figure"),
        })
    return pd.DataFrame(rows, columns=out_cols)


def demand_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(columns=["material_id", "demand_tpa", "plants_total", "plants_calculated", "data_status"])
    g = detail.groupby("material_id")
    s = pd.DataFrame({
        "demand_tpa": g.demand_tpa.sum(min_count=1).round(1),
        "plants_total": g.plant_id.nunique(),
        "plants_calculated": detail[detail.status == "Calculated"].groupby("material_id").plant_id.nunique(),
    }).fillna({"plants_calculated": 0}).reset_index()
    s["plants_calculated"] = s.plants_calculated.astype(int)

    def status(r):
        if r.plants_calculated == 0:
            return "Insufficient data"
        types = set(detail[(detail.material_id == r.material_id) & (detail.status == "Calculated")].quantity_type)
        partial = r.plants_calculated < r.plants_total
        if types == {"Reported"} and not partial:
            return "Verified (reported factors)"
        if "Engineering estimate" in types:
            return "Estimated"
        return "Partially verified"
    s["data_status"] = s.apply(status, axis=1)
    return s


if __name__ == "__main__":
    d = demand_detail()
    s = demand_summary(d)
    d.to_csv(PROCESSED / "demand_detail.csv", index=False)
    s.to_csv(PROCESSED / "demand_summary.csv", index=False)
    mats = load("materials").set_index("material_id").material_name
    print(s.assign(material=s.material_id.map(mats)).to_string(index=False) if len(s) else "No BOM data yet.")
