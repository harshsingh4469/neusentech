# NuSynth Technologies data dictionary

All tables live in `data/processed/` as CSV. IDs are created by the scripts; never type them by hand.

| Table | One row = | Key columns |
|---|---|---|
| sources | one downloaded document (one version) | source_id, title, publisher, url, document_date, local_file, sha256, status (current / superseded) |
| companies | one legal company | company_id, company_name, name_key (normalised name used for matching) |
| plants | one manufacturing site | plant_id, company_id, address, state, who_gmp_categories, manufacturing_status |
| products | one API / intermediate / KSM / formulation | product_id, product_name, category |
| plant_products | one capacity claim for one product at one plant from one document | capacity_value + capacity_unit (as printed), capacity_tpa (converted), capacity_basis, actual_output_tpa, evidence_status, source_id, page |
| materials | one raw material | material_id, material_name, material_category |
| bom | one consumption factor for product → material | kg_per_kg, quantity_type, plant_id (blank = applies to the product in general), source_id, page |
| evidence | one claim backed by one document | entity_type, entity_id, claim, raw_text (text copied from the PDF), confidence, page |
| conflicts | one disagreement between two documents | old_value, new_value, sources, resolution |

## Controlled values
- **category**: API, Intermediate, KSM, Formulation
- **capacity_basis**: EC approved · EC proposed · Consent to operate · Installed (company) · PLI committed
- **quantity_type**: Reported (kg/kg printed in source) · Calculated (derived from MT/month of material ÷ MT/month of product in the same document) · Engineering estimate (your documented stoichiometry/yield calculation) · Unknown
- **confidence**: Verified · Partially verified · Estimated · Requires validation

## Unit conversion (to tonnes per year)
MT/Month × 12 · Kg/Month × 0.012 · TPD or MT/day × 330 (assumes 330 operating days — state this when presenting) · TPA × 1

## Demand formula
D_m = Σ Q_i × r_i,m , where Q_i = actual output if reported, else the best capacity basis
(Consent to operate > Installed > EC approved > PLI committed > EC proposed), and r = kg material per kg product
(plant-specific factor first, product-level otherwise).
