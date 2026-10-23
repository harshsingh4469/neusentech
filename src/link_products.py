"""
Links intermediates and KSMs to the APIs they are used for.

    python3 src/link_products.py      (also runs automatically at the end of src/ingest.py)

Three kinds of link, rebuilt from scratch every run (the table is derived data):

 1. Name rule   - 'Metformin - INT', 'Sumatriptan intermediate'  -> intermediate of Metformin / Sumatriptan
 2. BOM         - a raw material that is ALSO made as a product in the dataset
                  (e.g. Para-aminophenol, made by Meghmani) -> raw material of Paracetamol
 3. Manual      - rows you approve in data/staging/manual_links.csv
                  (approve,intermediate_name,api_name,relation,source_id,note)
                  for links a name cannot reveal, e.g. 'Meta Chloropropiophenone' -> Bupropion

If the API is not in the dataset yet, the link is still kept with its name, so the
intermediate's page can say "intermediate of Metformin (API not yet in dataset)".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import STAGING, add_row, load, name_key, save  # noqa: E402

SALT_WORDS = {"hydrochloride", "hcl", "di", "dihydrochloride", "sodium", "potassium", "calcium", "fumarate",
              "maleate", "acetate", "sulphate", "sulfate", "bisulphate", "bisulfate", "besylate", "mesylate",
              "tartrate", "citrate", "phosphate", "monohydrate", "anhydrous", "bp", "ip", "usp", "ep", "base"}
INT_RE = re.compile(r"^(.*?)[\s\-–]*\b(int|intermediate|intermediates|stage[\s\-]*\w*|ksm)\b.*$", re.I)


def base_key(name: str) -> str:
    words = [w for w in name_key(name).split() if w not in SALT_WORDS]
    return "".join(words)          # no spaces: 'para amino phenol' == 'para-aminophenol'


def build() -> pd.DataFrame:
    prods, bom, mats = load("products"), load("bom"), load("materials")
    links = load("product_links").iloc[0:0]
    apis = prods[prods.category == "API"]
    api_by_base = {}
    for r in apis.itertuples():
        api_by_base.setdefault(base_key(r.product_name), r.product_id)
    seen = set()

    def add(frm, to_id, to_name, relation, method, sid="", note=""):
        nonlocal links
        key = (frm, to_id or to_name.lower(), relation)
        if frm and key not in seen and frm != to_id:
            seen.add(key)
            links, _ = add_row(links, "product_links", {
                "from_product_id": frm, "to_product_id": to_id, "to_product_name": to_name,
                "relation": relation, "method": method, "source_id": sid, "note": note})

    # 1. name rule
    for r in prods[prods.category.isin(["Intermediate", "KSM"])].itertuples():
        m = INT_RE.match(r.product_name)
        if not m or not m.group(1).strip():
            continue
        target = m.group(1).strip(" -–")
        to_id = api_by_base.get(base_key(target), "")
        to_name = prods.set_index("product_id").product_name.get(to_id, target) if to_id else target
        add(r.product_id, to_id, to_name, "intermediate of", "name rule",
            note="" if to_id else "API not yet in dataset")

    # 2. BOM: material that is also a product
    prod_by_key = {}
    for r in prods.itertuples():
        prod_by_key.setdefault(base_key(r.product_name), r.product_id)
    mat_key = dict(zip(mats.material_id, mats.material_name.map(base_key)))
    pname = prods.set_index("product_id").product_name
    for r in bom.itertuples():
        frm = prod_by_key.get(mat_key.get(r.material_id, ""), "")
        if frm:
            add(frm, r.product_id, pname.get(r.product_id, ""), "raw material of", "BOM", r.source_id)

    # 3. manual links
    f = STAGING / "manual_links.csv"
    if f.exists():
        man = pd.read_csv(f, dtype=str, keep_default_na=False)
        for r in man[man.get("approve", "").str.strip().str.upper() == "Y"].itertuples():
            frm = prod_by_key.get(base_key(r.intermediate_name), "")
            if not frm:
                print(f"  manual link skipped - '{r.intermediate_name}' is not a product in the dataset")
                continue
            to_id = api_by_base.get(base_key(r.api_name), "")
            add(frm, to_id, r.api_name, r.relation or "intermediate of", "manual",
                getattr(r, "source_id", ""), getattr(r, "note", ""))
    save("product_links", links)
    return links


if __name__ == "__main__":
    l = build()
    print(f"Product links: {len(l)} ({(l.to_product_id != '').sum()} to an API in the dataset, "
          f"{(l.to_product_id == '').sum()} to an API not yet in the dataset)")
