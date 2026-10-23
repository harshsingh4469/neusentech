"""
Read an Environmental Clearance (EC) letter / Form-1 / EIA report PDF and pull out
CANDIDATE facts for you to check:

  1. Product list with capacities      -> data/staging/review_capacity_<source_id>.csv
  2. Raw-material consumption tables   -> data/staging/review_bom_<source_id>.csv

    python3 src/extract_ec.py data/raw/ec/<file>.pdf

Nothing goes into the main dataset from here. You open the two review files,
check each row against the PDF page shown in the `page` column, fix anything
wrong, type Y in the `approve` column, then run src/ingest.py.
This "human in the loop" step is what makes the dataset trustworthy.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import STAGING, clean_unit, load, to_tpa  # noqa: E402
from download import sha256  # noqa: E402

UNIT_RE = r"(MT\s*/\s*Month|MT\s*/\s*Annum|MT\s*/\s*Year|MTPM|TPM|TPA|MT/M|Kg\s*/\s*Month|Kg\s*/\s*Day|Kg\s*/\s*Kg|MT\s*/\s*MT|Kg\s*/\s*Batch|TPD|Kg/Annum)"
NUM_RE = r"(\d[\d,]*\.?\d*)"
SKIP_WORDS = ("total", "grand total", "sub total", "subtotal", "s.no", "sr. no", "sl.no")


def clean(c) -> str:
    return re.sub(r"\s+", " ", str(c or "")).strip()


def num(text: str) -> str:
    m = re.search(NUM_RE, str(text))
    return m.group(1).replace(",", "") if m else ""


def unit_in(text: str) -> str:
    m = re.search(UNIT_RE, str(text), re.I)
    return m.group(1) if m else ""


def header_index(row, *words):
    """Column whose header contains one of `words` (earlier words win). Spaces are
    ignored because PDF headers often wrap or break mid-word."""
    squashed = [re.sub(r"\s+", "", c.lower()) for c in row]
    for w in words:
        w = w.replace(" ", "")
        for i, c in enumerate(squashed):
            if w in c:
                return i
    return None


def last_numeric_column(rows, skip):
    """Fallback: the right-most column where most cells are numbers."""
    width = max((len(r) for r in rows), default=0)
    for i in range(width - 1, -1, -1):
        if i == skip:
            continue
        cells = [r[i] for r in rows if i < len(r) and r[i]]
        if cells and sum(bool(re.fullmatch(r"[\d,.\s]+", c)) for c in cells) >= 0.6 * len(cells):
            return i
    return None


def guess_identity(full_text: str) -> dict:
    comp = re.search(r"M\s*/\s*s\.?\s+([A-Z][A-Za-z0-9&.,()\- ]{3,80}?(?:Limited|Ltd\.?|LLP|Pvt\.? Ltd\.?|Private Limited))", full_text)
    loc = re.search(r"(?:Location of (?:the )?Project|located at|situated at)\s*[:\-]?\s*([^\n]{10,160})", full_text, re.I)
    granted = re.search(r"grant of (?:prior )?environment(?:al)? clearance"
                        r"|accord(?:ed)? (?:the )?(?:prior )?environment(?:al)? clearance"
                        r"|environment(?:al)? clearance (?:is|has been) (?:hereby )?(?:granted|accorded)"
                        r"|EC Identification No", full_text, re.I)
    date = re.search(r"Date\s*[:\-]?\s*(\d{2}[/.\-]\d{2}[/.\-]\d{4})", full_text)
    return {
        "company_name": comp.group(1).strip() if comp else "",
        "plant_address": loc.group(1).strip() if loc else "",
        "capacity_basis": "EC approved" if granted else "EC proposed",
        "doc_date": date.group(1) if date else "",
    }


def product_tables(page, pno):
    rows = []
    for table in page.extract_tables():
        table = [[clean(c) for c in r] for r in table if r]
        for h, hdr in enumerate(table[:3]):
            p_i = header_index(hdr, "product", "name of the", "api")
            if p_i is None or header_index(hdr, "raw material") is not None:
                continue
            # capacity column: prefer 'total' / 'after expansion', else last column with a unit
            q_i = header_index(hdr, "total", "otal(", "after expansion", "capacity", "quantity", "production")
            if q_i is None or q_i == p_i:
                q_i = last_numeric_column(table[h + 1:], p_i)
            hdr_unit = unit_in(re.sub(r"\s+", "", " ".join(hdr)))
            if q_i is None:
                continue
            for r in table[h + 1:]:
                if any(re.search(r"by[- ]?product", c, re.I) for c in r):
                    break                                   # by-products are not manufactured products
                if len(r) <= max(p_i, q_i):
                    continue
                name, qty = tidy_name(r[p_i]), r[q_i]
                if not name or not num(qty) or name.lower().startswith(SKIP_WORDS) or re.fullmatch(NUM_RE, name):
                    continue
                unit = unit_in(qty) or hdr_unit
                if not unit:                                # e.g. water-balance tables (KLD) - not capacity
                    continue
                rows.append({"product_name": name, "capacity_value": num(qty), "capacity_unit": unit,
                             "page": pno, "raw_text": " | ".join(r)[:400]})
            break
    return rows


def product_lines(text, pno):
    """Fallback for PDFs without detectable tables: 'Paracetamol 300 MT/Month'."""
    rows = []
    pat = re.compile(rf"^\s*(?:\d+[.)]?\s+)?([A-Za-z][A-Za-z0-9,\-()\s']{{2,60}}?)\s+{NUM_RE}\s*{UNIT_RE}", re.I | re.M)
    for m in pat.finditer(text):
        name = clean(m.group(1))
        if name.lower().startswith(SKIP_WORDS) or "raw material" in name.lower():
            continue
        rows.append({"product_name": name, "capacity_value": m.group(2).replace(",", ""),
                     "capacity_unit": m.group(3), "page": pno, "raw_text": clean(m.group(0))})
    return rows


GRADE_RE = re.compile(r"\b(?:BP|IP|USP|EP|JP|Ph\.?\s?Eur)(?:\s*/\s*(?:BP|IP|USP|EP|JP))*\b\.?", re.I)
NOISE_RE = re.compile(r"^\s*(page\s*\d+.*|\d+\s*(of\s*\d+)?|ec identification.*)\s*$", re.I)


def tidy_name(name: str) -> str:
    name = re.split(r"\s+(?:SEIAA|Meeting\s+(?:No|Number|Date)|Page\s+\d+\s+of)\b", name)[0]   # page footers
    name = GRADE_RE.sub(" ", name)
    return clean(name).strip(" -–:,;")


def product_rows_from_text(texts):
    """Fallback for product tables WITHOUT ruling lines, read line by line.
       Handles rows where the name is on the same line ('1 Paracetamol 100 50 150')
       and rows where a long name wraps above/below the numbers:
           'Sodium Valproate' / '4 0.5 0 0.5' / 'BP/IP/USP'
       A header line with 'product' + a unit switches parsing on (it can span pages).
       With a 'Total' column the LAST number is used, otherwise the FIRST."""
    named = re.compile(r"^\s*\d{1,3}[.)]?\s+(.*?[A-Za-z]{3,}.*?)\s+(\d[\d,]*\.?\d*)(.*)$")
    bare = re.compile(r"^\s*\d{1,3}[.)]?\s+((?:\d[\d,]*\.?\d*\s*){1,6})$")
    rows, active, unit, take = [], False, "", "first"
    buf, prev_bare = [], False

    def value(numbers_text):
        nums = re.findall(r"(?<![A-Za-z\d.])(\d[\d,]*\.?\d*)(?![A-Za-z\d])", re.sub(r"\([^)]*\)", " ", numbers_text))
        return (nums[-1] if take == "last" else nums[0]).replace(",", "") if nums else ""

    def give_suffix():
        nonlocal buf
        if prev_bare and rows and len(buf) >= 2:
            k = len(buf) // 2
            rows[-1]["product_name"] = tidy_name(rows[-1]["product_name"] + " " + " ".join(buf[:k]))
            buf = buf[k:]

    for pno, text in enumerate(texts, start=1):
        for line in text.splitlines():
            low = line.lower()
            squashed = re.sub(r"\s+", "", line)
            if "product" in low and unit_in(squashed) and "raw" not in low:
                active, unit, buf, prev_bare = True, unit_in(squashed), [], False
                take = "last" if "total" in low else "first"
                continue
            if not active or NOISE_RE.match(line) or low.strip() in ("serial", "number", "sr. no.", "no."):
                continue
            if re.match(r"\s*(total|grand total|sub[- ]?total|raw material|by[- ]?product|note)\b", low):
                if prev_bare and rows and buf:
                    rows[-1]["product_name"] = tidy_name(rows[-1]["product_name"] + " " + buf[0])
                active, buf = False, []
                continue
            m_bare, m_named = bare.match(line), named.match(line)
            if m_bare:
                give_suffix()
                rows.append({"product_name": tidy_name(" ".join(buf)), "capacity_value": value(m_bare.group(1)),
                             "capacity_unit": unit, "page": pno, "raw_text": clean(" ".join(buf + [line]))[:400]})
                buf, prev_bare = [], True
            elif m_named:
                if prev_bare and rows and buf:      # lines between a wrapped name and a named row = its tail
                    rows[-1]["product_name"] = tidy_name(rows[-1]["product_name"] + " " + " ".join(buf))
                    rows[-1]["raw_text"] = clean(rows[-1]["raw_text"] + " " + " ".join(buf))[:400]
                    buf = []
                rows.append({"product_name": tidy_name(m_named.group(1)), "capacity_value": value(m_named.group(2) + m_named.group(3)),
                             "capacity_unit": unit, "page": pno, "raw_text": clean(line)[:400]})
                buf, prev_bare = [], False
            else:
                buf.append(clean(line))
                if len(buf) > 6:            # long run of non-table text = table ended
                    active, buf = False, []
    return [r for r in rows if r["product_name"] and r["capacity_value"]
            and not r["product_name"].lower().startswith(SKIP_WORDS)]


def bom_tables(page, pno, product_names):
    rows = []
    for t in page.find_tables():
        table = [[clean(c) for c in r] for r in t.extract() if r]
        if not table:
            continue
        hdr = table[0]
        m_i = header_index(hdr, "raw material", "name of raw", "material")
        q_i = header_index(hdr, "kg/kg", "consumption", "quantity", "mt/month", "qty")
        if m_i is None or q_i is None or m_i == q_i:
            continue
        p_col = header_index(hdr, "product")
        # which product does this table belong to? look at the text just above it
        above = page.crop((0, max(0, t.bbox[1] - 90), page.width, t.bbox[1])).extract_text() or ""
        # the product named closest above the table (last mention) wins
        low = above.lower()
        hits = [(low.rfind(p.lower()), p) for p in product_names if p and p.lower() in low]
        context_product = max(hits)[1] if hits else ""
        hdr_unit = unit_in(re.sub(r"\s+", "", " ".join(hdr)))
        for r in table[1:]:
            if len(r) <= max(m_i, q_i):
                continue
            mat, qty = r[m_i], r[q_i]
            if not mat or not num(qty) or mat.lower().startswith(SKIP_WORDS):
                continue
            rows.append({
                "product_name": (r[p_col] if p_col is not None and p_col < len(r) and r[p_col] else context_product),
                "material_name": mat, "quantity_value": num(qty),
                "quantity_unit": unit_in(qty) or hdr_unit, "page": pno, "raw_text": " | ".join(r)[:400],
            })
    return rows


def main(pdf_path: Path) -> None:
    sources = load("sources")
    src = sources[sources.sha256 == sha256(pdf_path)]
    if src.empty:
        sys.exit("Register the PDF first:  python3 src/download.py --register <file> --type ec ...")
    sid = src.source_id.iloc[0]

    caps, boms, full = [], [], []
    with pdfplumber.open(pdf_path) as pdf:
        texts = [(p.extract_text() or "") for p in pdf.pages]
        full = "\n".join(texts)
        scanned = [i for i, t in enumerate(texts, start=1) if len(t.strip()) < 80]
        if scanned:
            print(f"WARNING: {len(scanned)} of {len(texts)} pages have no text layer (scanned images): "
                  f"pages {scanned[0]}-{scanned[-1]}. Tables on those pages cannot be read without OCR.")
        text_pages = len(texts) - len(scanned)
        if text_pages == 0 or (len(texts) > 3 and text_pages <= 1):
            sys.exit("This PDF is basically a scan. Pick a text-based document, or type the rows by hand "
                     "(copy data/staging/templates/capacity_template.csv).")
        for pno, page in enumerate(pdf.pages, start=1):
            caps += product_tables(page, pno)
        if not caps:
            caps = product_rows_from_text(texts)
        if not caps:
            for pno, t in enumerate(texts, start=1):
                caps += product_lines(t, pno)
        names = sorted({c["product_name"] for c in caps}, key=len, reverse=True)
        for pno, page in enumerate(pdf.pages, start=1):
            boms += bom_tables(page, pno, names)

    ident = guess_identity(full)
    cap = pd.DataFrame(caps).drop_duplicates(subset=["product_name", "capacity_value", "capacity_unit"]) if caps else pd.DataFrame()
    if not cap.empty:
        cap.insert(0, "approve", "")
        cap["company_name"] = ident["company_name"]
        cap["plant_address"] = ident["plant_address"]
        cap["state"] = ""
        cap["product_category"] = cap.product_name.str.contains("intermediate|stage", case=False).map({True: "Intermediate", False: "API"})
        cap["capacity_tpa"] = [to_tpa(v, u) for v, u in zip(cap.capacity_value, cap.capacity_unit)]
        cap["capacity_basis"] = ident["capacity_basis"]
        cap["actual_output_tpa"] = ""
        cap["source_id"] = sid
        cap = cap[["approve", "company_name", "plant_address", "state", "product_name", "product_category",
                   "capacity_value", "capacity_unit", "capacity_tpa", "capacity_basis", "actual_output_tpa",
                   "source_id", "page", "raw_text"]]
        out = STAGING / f"review_capacity_{sid}.csv"
        cap.to_csv(out, index=False)
        print(f"{len(cap)} product/capacity candidates -> {out.relative_to(STAGING.parents[1])}")
    else:
        print("No product table found. Enter rows by hand using data/staging/templates/capacity_template.csv")

    bom = pd.DataFrame(boms)
    if not bom.empty:
        tpm = {}   # product -> capacity in MT/month, to turn MT/month of raw material into kg/kg
        for _, c in cap.iterrows() if not cap.empty else []:
            if c.capacity_tpa not in (None, ""):
                tpm[c.product_name.lower()] = float(c.capacity_tpa) / 12

        def factor(r):
            u = clean_unit(r.quantity_unit)
            v = float(r.quantity_value)
            if u in ("kg/kg", "mt/mt", "t/t"):
                return round(v, 4), "Reported"
            prod_tpm = tpm.get(str(r.product_name).lower())
            rm_tpa = to_tpa(v, u)
            if rm_tpa is not None and prod_tpm:
                return round(rm_tpa / 12 / prod_tpm, 4), "Calculated"
            return "", "Unknown"

        bom[["kg_per_kg", "quantity_type"]] = bom.apply(lambda r: pd.Series(factor(r)), axis=1)
        bom.insert(0, "approve", "")
        bom["company_name"] = ident["company_name"]
        bom["plant_address"] = ident["plant_address"]
        bom["material_category"] = "Raw material"
        bom["source_id"] = sid
        bom = bom[["approve", "company_name", "plant_address", "product_name", "material_name", "material_category",
                   "quantity_value", "quantity_unit", "kg_per_kg", "quantity_type", "source_id", "page", "raw_text"]]
        out = STAGING / f"review_bom_{sid}.csv"
        bom.to_csv(out, index=False)
        print(f"{len(bom)} raw-material candidates -> {out.relative_to(STAGING.parents[1])}")
    else:
        print("No raw-material table found in this document.")
    print(f"Guessed company: {ident['company_name'] or '(not found - type it in)'} | basis: {ident['capacity_basis']}")
    print("Next: open the review file(s), check each row against the PDF page, type Y in 'approve', then run src/ingest.py")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
