# Power BI views

SQL views that map pipeline tables to the feedback report templates (PDT / USER / DEALER groups).

| Artifact | Path |
|----------|------|
| View DDL | [`scripts/sql/pbi_views.sql`](../scripts/sql/pbi_views.sql) |
| Apply helper (local) | [`scripts/apply_pbi_views.py`](../scripts/apply_pbi_views.py) |
| Apply helper (GCP) | [`scripts/apply_pbi_views_gcp.sh`](../scripts/apply_pbi_views_gcp.sh) |
| Taxonomy seed | [`scripts/data/feedback_taxonomy.json`](../scripts/data/feedback_taxonomy.json) |
| Local target | Postgres DB `pidilite_gcp_20260810` (Cloud dump; see [`.db-dumps/README_LOCAL_GCP_DB.txt`](../.db-dumps/README_LOCAL_GCP_DB.txt); older `pidilite_gcp` kept) |
| GCP target | Cloud SQL `user-feedback-db` (via Cloud Run job `pidilite-pipeline-migrate`) |

---

## Prerequisites

1. Local Postgres container running (`user_feedback_batchmicro-db-1` on port `5432`).
2. Cloud dump loaded into a **separate** database named `pidilite_gcp` (not your day-to-day `pidilite` DB).
3. Docker available for `docker exec … psql`.

---

## Apply steps

```bash
# From repo root
python scripts/apply_pbi_views.py \
  --docker-container user_feedback_batchmicro-db-1 \
  --db pidilite_gcp \
  --user postgres
```

This will:

1. Create / truncate `bi_feedback_taxonomy` and seed it from `feedback_taxonomy.json`.
2. Create / replace all `vw_pbi_*` views from `scripts/sql/pbi_views.sql`.
3. Print row counts for a quick sanity check.

Manual alternative:

```bash
# Seed + views via psql inside the container
docker exec -i user_feedback_batchmicro-db-1 \
  psql -U postgres -d pidilite_gcp -v ON_ERROR_STOP=1 \
  < scripts/sql/pbi_views.sql

# Taxonomy seed still requires the Python helper (or hand-rolled INSERTs)
python scripts/apply_pbi_views.py --db pidilite_gcp
```

Connect to verify:

```bash
docker exec -it user_feedback_batchmicro-db-1 psql -U postgres -d pidilite_gcp
\dv vw_pbi*
SELECT * FROM vw_pbi_tag_counts ORDER BY feedback_group, feedback_count DESC LIMIT 20;
```

### Apply on GCP (Cloud SQL)

Cloud SQL is private-IP only, so apply runs inside the migrate Cloud Run job:

```bash
./scripts/apply_pbi_views_gcp.sh
```

Notes:

- Cloud SQL `feedback_tags` uses integer PK `tag_id` (taxonomy IDs). Local/ORM uses UUID `id`. The apply helpers rewrite the fact-view join accordingly.
- The script temporarily overrides `pidilite-pipeline-migrate`, runs seed + views, then restores `poetry run python scripts/migrate_schema.py`.

---

## View catalog (which report uses which)

| Power BI report shape (from templates) | Recommended view | Grain |
|----------------------------------------|------------------|-------|
| Tag matrix with counts (all groups), including **0** for unused tags | `vw_pbi_taxonomy_coverage` | 1 row per taxonomy tag |
| Tag counts (only tags that have data) | `vw_pbi_tag_counts` | group × category × tag × sub_tag |
| PDT by **product** × category × tag | `vw_pbi_pdt_product_counts` | product × tag dims |
| Detail: AI summary + excerpt + full conversation | `vw_pbi_feedback_detail` | feedback × tag |
| PDT / USER / DEALER filtered detail | `vw_pbi_pdt_detail`, `vw_pbi_user_detail`, `vw_pbi_dealer_detail` | same |
| PDT / USER / DEALER filtered tag counts | `vw_pbi_pdt_tag_counts`, `vw_pbi_user_tag_counts`, `vw_pbi_dealer_tag_counts` | same as tag_counts |
| Universal fact (build any matrix in PBI) | `vw_pbi_feedback_fact` | feedback × tag |

**Totals** such as “Total Marine = 14” or “Total Dealer related = 50” should be computed in Power BI (matrix visual subtotals / measures), not hard-coded in SQL.

---

## Column mapping

| Report column | View column | Source |
|---------------|-------------|--------|
| FEEDBACK GROUP | `feedback_group` | `feedback_tags.group_type`, else `feedbacks.group_type` |
| Feedback category | `feedback_category` | `feedback_tags.category`, else `feedbacks.category_type` |
| Feedback Tag | `feedback_tag` | `feedback_tags.tag_name` |
| Feedback sub Tag | `feedback_sub_tag` | `feedback_tags.sub_tag_name` |
| Product Name | `product_name` | `feedbacks.product_name` / `products.product_name` |
| Feedback Count | `feedback_count` | `COUNT(DISTINCT feedback_id)` |
| Feedback summary (AI generated) | `feedback_summary_ai` | `feedbacks.ai_summary` |
| Feedback voice recording (Excerpt) | `feedback_excerpt` | `feedbacks.verbatim_quote` |
| Full Conversation | `full_conversation` | `processed_file.translated_text` |
| Competitors (for PDT competition tags) | `competitors_mentioned` | `feedback_competitors` aggregated |

Geo / call filters available on fact/detail views: `call_date`, `state`, `division`, `zone`, `cluster`, `rfmm_cluster`, `town_city`, `fme_code`, `user_type`, `data_source`.

---

## Example queries

### PDT tag counts (template without product)

```sql
SELECT
  feedback_group,
  feedback_category,
  feedback_tag,
  feedback_count
FROM vw_pbi_pdt_tag_counts
ORDER BY feedback_category, feedback_tag;
```

### PDT taxonomy with zeros (empty count cells in template)

```sql
SELECT
  feedback_group,
  feedback_category,
  feedback_tag,
  feedback_sub_tag,
  feedback_count
FROM vw_pbi_taxonomy_coverage
WHERE feedback_group = 'PDT GROUP'
ORDER BY feedback_category, feedback_tag;
```

### PDT by product (Marine / FV style)

```sql
SELECT
  feedback_group,
  product_name,
  feedback_category,
  feedback_tag,
  feedback_count
FROM vw_pbi_pdt_product_counts
WHERE product_name IS NOT NULL
ORDER BY product_name, feedback_category, feedback_tag;
```

### Product subtotal in SQL (optional; prefer Power BI)

```sql
SELECT product_name, SUM(feedback_count) AS product_total
FROM vw_pbi_pdt_product_counts
WHERE product_name IS NOT NULL
GROUP BY product_name
ORDER BY product_name;
```

### Detail tab (AI summary + excerpt + full conversation)

```sql
SELECT
  feedback_category,
  feedback_tag,
  feedback_sub_tag,
  product_name,
  competitors_mentioned,
  feedback_summary_ai,
  feedback_excerpt,
  left(full_conversation, 500) AS full_conversation_preview
FROM vw_pbi_pdt_detail
ORDER BY feedback_category, feedback_tag, product_name;
```

### USER / DEALER tag matrices

```sql
SELECT * FROM vw_pbi_user_tag_counts ORDER BY feedback_category, feedback_tag;
SELECT * FROM vw_pbi_dealer_tag_counts ORDER BY feedback_category, feedback_tag;
```

---

The live database is not on the public internet. What Power BI needs in production is described in [hld-and-powerbi-access.md](hld-and-powerbi-access.md). The steps below are for a local copy used while building reports.

## Connect Power BI Desktop (local dump)

1. **Get data** → **PostgreSQL database**
2. Server: `localhost` (or host running Docker)  
   Database: `pidilite_gcp`  
   Port: `5432`
3. Auth: Database user `postgres` + your local password (from `.env` `DB_PASSWORD`)
4. Select views:
   - Start with `vw_pbi_feedback_fact` (one model, many visuals), **or**
   - Import specialized views (`vw_pbi_taxonomy_coverage`, `vw_pbi_pdt_product_counts`, `vw_pbi_feedback_detail`, …)
5. In Power BI:
   - Use a **Matrix** visual: rows = group → category → tag (→ sub tag / product)
   - Values = `Count of feedback_id` (from fact) or `Sum of feedback_count` (from count views)
   - Enable row subtotals for “Total Marine”, “Total User Meet”, etc.

---

## Re-apply after a fresh Cloud dump

```bash
# 1) Reload dump into pidilite_gcp (see .db-dumps/README_LOCAL_GCP_DB.txt)
# 2) Re-apply views + taxonomy
python scripts/apply_pbi_views.py --db pidilite_gcp
```

Views are `CREATE OR REPLACE`; taxonomy is truncated and re-seeded.

---

## Notes / caveats

- Prefer **tag** `group_type` / `category` over `feedbacks.group_type` / `category_type` — LLM rows sometimes store `Product` in `group_type` while tags correctly say `PDT GROUP`.
- Untagged feedbacks appear as `feedback_tag = '(untagged)'` in the fact view.
- `feedback_sub_tag` is often null in current data; taxonomy `feedback_sub_tag` on coverage view holds the guidance text from the Excel templates.
- Cloud SQL PG18 → local PG15 dump may leave minor type quirks; views use portable SQL only.
