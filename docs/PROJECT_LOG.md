# Pharma Raw-Material Intelligence Platform — project log (prompts, decisions, results)

Fill one entry every time you work on the project. This file is your proof of *how* you reached the result.
Interviewers care more about your reasoning and checks than about the final screen.

---

## Entry template

**Date:**
**Goal of this session:**
**Prompt I used (copy exactly):**
> ...

**What the AI suggested (2–3 lines, your words):**

**What I accepted / changed / rejected — and why:**

**What I ran (commands):**

**Result (paste the `Added:` line, numbers, screenshot name):**

**How I verified it (which PDF page I checked):**

**Problems & how I fixed them:**

---

## Entry 1 — Problem framing  (example, edit to your own words)

**Goal:** Turn the brief into a data model.
**Decision:** Separate tables for companies, plants, products, plant_products, materials, BOM, evidence.
**Why:** One company has many plants; one plant has many products; one product has many inputs. A single
sheet would duplicate data and make totals wrong.

## Entry 2 — Why the first version showed only 7 products

**Observation:** Dashboard showed 2,330 companies and 3,454 plants but only 7 products.
**Cause:** The WHO-GMP list gives companies and plants but does not say *which API* each plant makes.
Product-level evidence only came from the 6-row PLI file.
**Fix:** Added Environmental Clearance documents (PARIVESH) as the main product + capacity + raw-material
source, with a review-and-approve step.

## Entry 3 — Capacity totals were mixing different things
**Observation:** Dashboard summed capacities of different products and different bases into one number.
**Fix:** Chart is now grouped by product and basis; totals use one figure per plant-product.

## Key limitations (say these out loud in the interview)
- EC capacity is a legal *maximum*, not production.
- Public coverage is partial; totals are "capacity represented in this dataset", not India's capacity.
- Some EC PDFs are scanned images and need OCR or manual entry.
- Consumption factors from EC documents are company declarations; "Calculated" factors depend on the document's own monthly figures.
