"""
NuSynth Technologies - Pharmaceutical Manufacturing & Raw-Material Intelligence (India)

Run from the project folder:   streamlit run app/streamlit_app.py
Every number on every page is computed from data/processed/*.csv - nothing is hard-coded.
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import json  # noqa: E402

from demand import best_output, demand_detail, demand_summary  # noqa: E402
from link_products import base_key  # noqa: E402
from schema import ROOT, STAGING, load  # noqa: E402

APP_NAME = "NuSynth Technologies"   # change the brand name here only
st.set_page_config(page_title=APP_NAME, page_icon="⚗️", layout="wide")


@st.cache_data
def data():
    t = {n: load(n) for n in ["sources", "companies", "plants", "products", "plant_products",
                               "materials", "bom", "evidence", "conflicts", "product_links", "leads"]}
    t["detail"] = demand_detail()
    t["summary"] = demand_summary(t["detail"])
    return t


D = data()
src, comp, plants, prods, pp = D["sources"], D["companies"], D["plants"], D["products"], D["plant_products"]
mats, bom, ev, detail, summary = D["materials"], D["bom"], D["evidence"], D["detail"], D["summary"]

company_name = comp.set_index("company_id").company_name
plant_addr = plants.set_index("plant_id").address
plant_state = plants.set_index("plant_id").state
plant_company = plants.set_index("plant_id").company_id
product_name = prods.set_index("product_id").product_name
product_cat = prods.set_index("product_id").category
material_name = mats.set_index("material_id").material_name
src_title = src.set_index("source_id").title
src_url = src.set_index("source_id").url
src_date = src.set_index("source_id").document_date
links = D["product_links"]
prod_by_base = {}
for _r in prods.itertuples():
    prod_by_base.setdefault(base_key(_r.product_name), _r.product_id)


def num(s):
    return pd.to_numeric(s, errors="coerce")


def with_names(df):
    df = df.copy()
    if "plant_id" in df:
        df["company"] = df.plant_id.map(plant_company).map(company_name)
        df["plant_location"] = df.plant_id.map(plant_addr)
        df["state"] = df.plant_id.map(plant_state)
    if "product_id" in df:
        df["product"] = df.product_id.map(product_name)
        df["category"] = df.product_id.map(product_cat)
    if "material_id" in df:
        df["material"] = df.material_id.map(material_name)
    if "source_id" in df:
        df["source"] = df.source_id.map(src_title)
        df["document_date"] = df.source_id.map(src_date)
        df["link"] = df.source_id.map(src_url)
    return df


LINK = {"link": st.column_config.LinkColumn("link", display_text="open")}


def supply(product_id):
    """Who makes this product in the dataset, and how much (one figure per plant, best basis)."""
    q = best_output(pp[pp.product_id == product_id])
    if q.empty:
        return {"makers": "none in dataset yet", "plants": 0, "capacity_tpa": None, "bases": ""}
    q = with_names(q)
    return {"makers": ", ".join(sorted(q.company.dropna().unique())), "plants": q.plant_id.nunique(),
            "capacity_tpa": round(num(q.Q).sum(min_count=1), 1), "bases": ", ".join(sorted(set(q.Q_basis)))}


def show_sources(ids):
    s = src[src.source_id.isin(set(ids))][["source_id", "title", "publisher", "document_date", "url", "local_file"]].copy()
    s["url"] = s.url.where(s.url.str.startswith("http"), None)   # own calculations: see local_file instead
    if s.empty:
        st.caption("No sources recorded.")
    else:
        st.dataframe(s, hide_index=True, width="stretch",
                     column_config={"url": st.column_config.LinkColumn("url", display_text="open document")})


# ------------------------------------------------------------------ header
st.title(APP_NAME)
st.caption("Pharmaceutical manufacturing and raw-material intelligence for India, built only from public documents. "
           "Capacity figures are labelled by basis (EC approved, installed, PLI committed...) and are never mixed "
           "with actual production.")
if st.button("Reload data"):
    st.cache_data.clear(); st.rerun()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Dashboard", "Product search", "Company and plant",
                                        "Raw-material demand", "Data quality and sources"])

# ------------------------------------------------------------------ 1 dashboard
with tab1:
    product_ev_plants = pp.plant_id.nunique()
    c = st.columns(6)
    c[0].metric("Companies", f"{len(comp):,}")
    c[1].metric("Plants identified", f"{len(plants):,}")
    c[2].metric("Plants with product evidence", f"{product_ev_plants:,}")
    c[3].metric("Products (API / int. / form.)", f"{len(prods):,}")
    c[4].metric("Raw materials mapped", f"{len(mats):,}")
    c[5].metric("Verified evidence records", f"{(ev.confidence == 'Verified').sum():,}",
                help=f"{len(ev):,} evidence records in total")
    if len(prods):
        st.caption("Products by category: " + ", ".join(f"{k}: {v}" for k, v in prods.category.value_counts().items()))

    st.subheader("Documented capacity by product and basis")
    if pp.empty:
        st.info("No product capacity records yet. Extract an EC document or fill a capacity template, then run src/ingest.py.")
    else:
        cap = with_names(pp.assign(capacity_tpa=num(pp.capacity_tpa)).dropna(subset=["capacity_tpa"]))
        by = cap.groupby(["product", "capacity_basis"], as_index=False).capacity_tpa.sum()
        top_n = st.slider("Products shown (largest documented capacity first)", 5, max(5, by["product"].nunique()),
                          min(15, max(5, by["product"].nunique())))
        order = by.groupby("product").capacity_tpa.sum().sort_values(ascending=False).head(top_n).index.tolist()
        show = by[by["product"].isin(order)]
        fig = px.bar(show, y="product", x="capacity_tpa", color="capacity_basis", orientation="h", barmode="group",
                     category_orders={"product": order}, height=max(320, 28 * len(order) + 120),
                     labels={"capacity_tpa": "tonnes / year (log scale)", "product": "", "capacity_basis": "basis"},
                     log_x=st.toggle("Log scale (makes small capacities visible)", value=True))
        fig.update_layout(legend=dict(orientation="h", y=-0.15), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption("Each basis gets its own bar; bases are never added into one 'total'. "
                   "Each figure comes from one document; see Product search for the source.")

        pick = st.multiselect("Total for selected products (one figure per plant, best basis, no double counting)",
                              sorted(cap["product"].unique()))
        if pick:
            q = with_names(best_output(pp))
            q = q[q["product"].isin(pick)]
            st.metric("Capacity represented in this dataset (t/yr)", f"{q.Q.sum():,.0f}",
                      help="Sum over plants in the dataset - NOT total Indian capacity.")
            st.dataframe(q.groupby(["product", "Q_basis"]).agg(plants=("plant_id", "nunique"), tonnes_per_year=("Q", "sum")),
                         width="stretch")
        st.caption("These totals cover only the plants in this dataset, not total Indian capacity.")

# ------------------------------------------------------------------ 2 product search
with tab2:
    if prods.empty:
        st.info("No products yet.")
    else:
        choice = st.selectbox("Search an API, intermediate or formulation", sorted(prods.product_name),
                              index=None, placeholder="type e.g. Paracetamol")
        if choice:
            pid = prods.loc[prods.product_name == choice, "product_id"].iloc[0]
            cat = product_cat[pid]
            rows = with_names(pp[pp.product_id == pid])
            q = best_output(pp[pp.product_id == pid])
            st.subheader(f"{choice}  ·  {cat}")
            if cat == "API":
                st.caption("Shows plants with evidence of making the API itself. Companies that only make "
                           "finished tablets from bought-in API are NOT counted here.")
            m = st.columns(4)
            m[0].metric("Companies", rows.company.nunique())
            m[1].metric("Plants", rows.plant_id.nunique())
            m[2].metric("Capacity in dataset (t/yr)", f"{num(q.Q).sum():,.0f}" if len(q) else "–")
            act = num(rows.actual_output_tpa).sum(min_count=1)
            m[3].metric("Reported actual production (t/yr)", f"{act:,.0f}" if pd.notna(act) else "not reported")

            st.markdown("**A. Manufacturers and plants**")
            st.dataframe(rows[["company", "plant_location", "state", "capacity_value", "capacity_unit", "capacity_tpa",
                               "capacity_basis", "actual_output_tpa", "evidence_status", "document_date", "source", "page", "link"]]
                         .sort_values("document_date", ascending=False),
                         hide_index=True, width="stretch", column_config=LINK)
            st.caption("Older documents for the same plant are kept as historical evidence of manufacturing.")

            st.markdown("**B. Manufacturing inputs (raw materials and intermediates)**")
            b = with_names(bom[bom.product_id == pid])
            if b.empty:
                st.write("No publicly documented inputs recorded yet for this product.")
            else:
                b["applies_to"] = b.plant_id.map(lambda x: f"{company_name.get(plant_company.get(x), '')} plant" if x else "Product level")
                st.dataframe(b[["material", "quantity_value", "quantity_unit", "kg_per_kg", "quantity_type",
                                "applies_to", "source", "page", "link"]], hide_index=True, width="stretch",
                             column_config=LINK)

            st.markdown("**Associated intermediates and KSMs**")
            inn = links[links.to_product_id == pid]
            out = links[links.from_product_id == pid]
            if inn.empty and out.empty:
                st.write("No linked intermediates or KSMs yet.")
            if len(inn):
                rows_in = []
                for l in inn.itertuples():
                    sup = supply(l.from_product_id)
                    rows_in.append({"input": product_name.get(l.from_product_id), "category": product_cat.get(l.from_product_id),
                                    "relation": l.relation, "how linked": l.method, "made in dataset by": sup["makers"],
                                    "plants": sup["plants"], "capacity_tpa": sup["capacity_tpa"], "capacity basis": sup["bases"]})
                st.dataframe(pd.DataFrame(rows_in), hide_index=True, width="stretch")
                st.caption("Upstream products that feed this one, and how much of them the plants in this dataset can make.")
            if len(out):
                rows_out = [{"used for": l.to_product_name, "relation": l.relation, "how linked": l.method,
                             "API in dataset": "yes" if l.to_product_id else "not yet", "note": l.note}
                            for l in out.itertuples()]
                st.dataframe(pd.DataFrame(rows_out), hide_index=True, width="stretch")
                st.caption("Downstream: the API(s) this intermediate or KSM is used to make.")

            st.markdown("**C. Estimated annual input demand from the plants in this dataset**")
            d = with_names(detail[detail.product_id == pid])
            if d.empty:
                st.write("Needs both a capacity and a consumption factor.")
            else:
                d["factor_type"] = d.quantity_type.where(d.status == "Calculated", "-")
                st.dataframe(d.groupby(["material", "factor_type", "status"], as_index=False)
                             .agg(plants=("plant_id", "nunique"),
                                  capacity_bases=("Q_basis", lambda s: ", ".join(sorted(set(s)))),
                                  demand_tpa=("demand_tpa", lambda s: round(s.sum(min_count=1), 1))),
                             hide_index=True, width="stretch")
                st.caption("factor_type shows how the kg-per-kg factor was obtained (Reported > Calculated > "
                           "Engineering estimate). An engineering estimate from stoichiometry is a theoretical minimum.")

            st.markdown("**D. Sources**")
            show_sources(list(rows.source_id) + list(b.source_id if len(b) else []))

# ------------------------------------------------------------------ 3 company and plant
with tab3:
    if comp.empty:
        st.info("No companies yet.")
    else:
        only_ev = st.toggle("Only companies with product evidence", value=True)
        cids = plants[plants.plant_id.isin(pp.plant_id)].company_id.unique() if only_ev else comp.company_id
        opts = comp[comp.company_id.isin(cids)].sort_values("company_name")
        cname = st.selectbox("Company", opts.company_name, index=None, placeholder="type to search")
        if cname:
            cid = opts.loc[opts.company_name == cname, "company_id"].iloc[0]
            my = plants[plants.company_id == cid]
            st.write(f"**{len(my)}** plant(s) recorded")
            label = {r.plant_id: f"{r.plant_id} · {r.address[:90]}" for r in my.itertuples()}
            plant_id = st.radio("Plant", list(label), format_func=label.get)
            p = my[my.plant_id == plant_id].iloc[0]
            st.markdown(f"**Location:** {p.address}  \n**State:** {p.state or '–'}  \n"
                        f"**Status:** {p.manufacturing_status}  \n**WHO-GMP categories:** {p.who_gmp_categories or '–'}")
            pr = with_names(pp[pp.plant_id == plant_id])
            st.markdown("**Products at this plant**")
            if pr.empty:
                st.write("No product-level evidence yet (certification alone does not show which products are made).")
            else:
                st.dataframe(pr[["product", "category", "capacity_tpa", "capacity_basis", "actual_output_tpa",
                                 "evidence_status", "document_date", "source", "page", "link"]],
                             hide_index=True, width="stretch", column_config=LINK)
            dd = with_names(detail[detail.plant_id == plant_id])
            if len(dd):
                st.markdown("**Raw-material requirement (documented or calculated)**")
                st.dataframe(dd[["product", "material", "Q", "Q_basis", "r", "quantity_type", "factor_level", "demand_tpa", "status"]],
                             hide_index=True, width="stretch")
            st.markdown("**Evidence**")
            e = with_names(ev[ev.entity_id.isin([plant_id] + list(pr.pp_id))])
            st.dataframe(e[["claim", "confidence", "document_date", "source", "page", "link"]],
                         hide_index=True, width="stretch", column_config=LINK)

# ------------------------------------------------------------------ 4 raw-material demand
with tab4:
    if summary.empty:
        st.info("No raw-material data yet. Approve rows in a review_bom file and run src/ingest.py.")
    else:
        s = with_names(summary)
        s["annual_demand"] = s.demand_tpa.map(lambda v: f"{v:,.1f} t/yr" if pd.notna(v) else "Insufficient data")
        sup = s.material.map(lambda m: supply(prod_by_base[base_key(m)]) if base_key(m) in prod_by_base else None)
        s["supply_in_dataset"] = sup.map(lambda x: f"{x['capacity_tpa']:,.0f} t/yr ({x['bases']})"
                                         if x and x["capacity_tpa"] else "no makers in dataset yet")
        s["makers"] = sup.map(lambda x: x["makers"] if x else "")
        st.dataframe(s[["material", "annual_demand", "plants_calculated", "plants_total", "data_status",
                        "supply_in_dataset", "makers"]]
                     .rename(columns={"plants_calculated": "plants with figures", "plants_total": "plants linked"}),
                     hide_index=True, width="stretch")
        st.caption("supply_in_dataset = capacity of plants in this dataset that make the material itself. "
                   "Integrated makers also produce it for their own use, so demand and supply do not net off.")
        st.caption("Demand = Σ (plant output Q × kg of material per kg of product r). Rows without Q or r are "
                   "shown as gaps, never as zero. This is estimated consumption, not confirmed purchasing.")
        mat = st.selectbox("Drill into a material", sorted(s.material))
        mid = mats.loc[mats.material_name == mat, "material_id"].iloc[0]
        d = with_names(detail[detail.material_id == mid])
        st.dataframe(d[["product", "company", "plant_location", "Q", "Q_basis", "r", "quantity_type",
                        "factor_level", "demand_tpa", "status"]], hide_index=True, width="stretch")
        ok = d.dropna(subset=["demand_tpa"])
        if len(ok):
            st.plotly_chart(px.bar(ok, x="company", y="demand_tpa", color="product",
                                   labels={"demand_tpa": "tonnes / year", "company": ""}), width="stretch")

# ------------------------------------------------------------------ 5 data quality
with tab5:
    a, b2, c2 = st.columns(3)
    a.metric("Source documents", len(src))
    b2.metric("Open conflicts", int((D["conflicts"].resolution == "open").sum()))
    waiting = 0
    for f in STAGING.glob("*.csv"):
        x = pd.read_csv(f, dtype=str, keep_default_na=False)
        if "approve" in x:
            waiting += int((x.approve.str.strip().str.upper() != "Y").sum())
    c2.metric("Staging rows not yet approved", waiting)
    st.markdown("**Last automatic update check**")
    lu = ROOT / "logs" / "last_update.json"
    try:
        u = json.loads(lu.read_text())
        st.write(f"Run at **{u['run_at']}** — {len(u['changed'])} changed, {len(u['unchanged'])} unchanged, "
                 f"{len(u['skipped_robots']) + len(u['failed'])} need a manual check, "
                 f"{len(u['not_checkable'])} not checkable (own files).")
        for k, label in [("changed", "Changed"), ("skipped_robots", "Blocked by robots.txt"), ("failed", "Could not re-download")]:
            if u[k]:
                st.caption(f"{label}: " + "; ".join(u[k]))
    except Exception:
        st.caption("No update run yet. Run ./run_update.sh")
    leads = D["leads"]
    st.markdown(f"**New document leads** ({int((leads.status == 'new').sum())} waiting)")
    if leads.empty:
        st.caption("No leads yet. Run python3 src/discover.py")
    else:
        st.dataframe(leads[["lead_id", "status", "source_type", "title", "url", "found_on", "discovered_on"]]
                     .sort_values("discovered_on", ascending=False), hide_index=True, width="stretch",
                     column_config={"url": st.column_config.LinkColumn("url", display_text="open")})
        st.caption("Download a lead: python3 src/download.py --lead LD00001 · ignore: --skip-lead LD00001")
    st.markdown("**Evidence by confidence**")
    st.dataframe(ev.confidence.value_counts().rename_axis("confidence").reset_index(name="records"), hide_index=True)
    if len(D["conflicts"]):
        st.markdown("**Conflicts between documents** (old value kept until you accept the new one)")
        st.dataframe(D["conflicts"], hide_index=True, width="stretch")
    st.markdown("**All source documents**")
    show_sources(src.source_id)
