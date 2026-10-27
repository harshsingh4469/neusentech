# NuSynth Technologies — Pharmaceutical Manufacturing & Raw-Material Intelligence (India)

Maps Indian pharmaceutical manufacturers → their plants → the APIs / intermediates they make →
documented capacities → the raw materials those products consume → aggregated raw-material demand.
Built **only from public documents**, with every figure traceable to a source PDF and page.

## Pipeline

```
sources_list.csv ──► src/download.py ──► data/raw/            (original PDFs, SHA-256 fingerprinted)
                                         │
     WHO-GMP list ──► src/extract_who_gmp.py ──► companies + plants (certified units)
     EC / Form-1  ──► src/extract_ec.py ──► data/staging/review_*.csv   (candidates)
     annual report / PLI / website ──► data/staging/manual_*.csv (typed by hand from templates)
                                         │  you check each row and type Y in `approve`
                                         ▼
                      src/ingest.py ──► data/processed/*.csv   (+ conflicts.csv)
                      src/demand.py ──► demand_detail.csv, demand_summary.csv
                      app/streamlit_app.py ──► the website
                      run_update.sh ──► weekly re-check of every source
```

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 src/download.py
python3 src/extract_who_gmp.py data/raw/who_gmp/<file>.pdf
python3 src/extract_ec.py data/raw/ec/<file>.pdf        # then review + approve
python3 src/ingest.py
python3 src/demand.py
streamlit run app/streamlit_app.py
```

## Rules the data follows
- Capacity ≠ production. `capacity_tpa` and `actual_output_tpa` are separate columns.
- Every capacity carries a basis: EC approved, EC proposed, Consent to operate, Installed (company), PLI committed.
- One figure per plant-product when totalling (best basis wins) → no double counting.
- API ≠ formulation. A tablet maker is never counted as an API maker.
- Consumption factors are labelled Reported / Calculated / Engineering estimate / Unknown. Unknown is shown as a gap, never as zero.
- New documents never overwrite old values silently; disagreements go to `conflicts.csv`.

See `docs/DATA_DICTIONARY.md` and `docs/PROJECT_LOG.md`.
