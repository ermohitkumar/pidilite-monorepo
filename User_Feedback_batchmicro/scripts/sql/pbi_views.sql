-- Power BI reporting views for Pidilite feedback pipeline
-- Target DB: pidilite_gcp (or any DB with the pipeline schema)
-- Apply:  psql -U postgres -d pidilite_gcp -f scripts/sql/pbi_views.sql

BEGIN;

-- Drop views first so CREATE OR REPLACE can change column lists safely
DROP VIEW IF EXISTS vw_pbi_dealer_tag_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_user_tag_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_pdt_tag_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_dealer_detail CASCADE;
DROP VIEW IF EXISTS vw_pbi_user_detail CASCADE;
DROP VIEW IF EXISTS vw_pbi_pdt_detail CASCADE;
DROP VIEW IF EXISTS vw_pbi_taxonomy_coverage CASCADE;
DROP VIEW IF EXISTS vw_pbi_feedback_detail CASCADE;
DROP VIEW IF EXISTS vw_pbi_pdt_product_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_tag_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_feedback_counts CASCADE;
DROP VIEW IF EXISTS vw_pbi_feedback_fact_slim CASCADE;
DROP VIEW IF EXISTS vw_pbi_feedback_fact CASCADE;

-- ── Taxonomy dimension (seeded separately from feedback_taxonomy.json) ───────
CREATE TABLE IF NOT EXISTS bi_feedback_taxonomy (
    tag_id              INTEGER PRIMARY KEY,
    feedback_group      VARCHAR(100) NOT NULL,
    feedback_category   VARCHAR(100) NOT NULL,
    feedback_tag        VARCHAR(300) NOT NULL,
    feedback_sub_tag    TEXT,
    description         TEXT
);

CREATE INDEX IF NOT EXISTS ix_bi_taxonomy_group ON bi_feedback_taxonomy (feedback_group);
CREATE INDEX IF NOT EXISTS ix_bi_taxonomy_category ON bi_feedback_taxonomy (feedback_category);
CREATE INDEX IF NOT EXISTS ix_bi_taxonomy_tag ON bi_feedback_taxonomy (feedback_tag);

-- ── Fact grain: one row per feedback × tag (Power BI detail + measures) ─────
CREATE OR REPLACE VIEW vw_pbi_feedback_fact AS
SELECT
    f.id                                              AS feedback_id,
    f.job_id,
    f.created_at                                      AS feedback_created_at,

    -- Prefer tag taxonomy fields; fall back to feedback row fields
    COALESCE(NULLIF(TRIM(t.group_type), ''), NULLIF(TRIM(f.group_type), ''), 'UNKNOWN')
                                                      AS feedback_group,
    COALESCE(NULLIF(TRIM(t.category), ''), NULLIF(TRIM(f.category_type), ''), 'UNKNOWN')
                                                      AS feedback_category,
    COALESCE(NULLIF(TRIM(t.tag_name), ''), '(untagged)')
                                                      AS feedback_tag,
    NULLIF(TRIM(t.sub_tag_name), '')                  AS feedback_sub_tag,

    COALESCE(NULLIF(TRIM(f.product_name), ''), p.product_name)
                                                      AS product_name,
    f.product_id,
    p.short_code                                      AS product_short_code,

    f.ai_summary                                      AS feedback_summary_ai,
    f.verbatim_quote                                  AS feedback_excerpt,
    pf.translated_text                                AS full_conversation,
    pf.raw_transcript_text                            AS full_conversation_raw,
    pf.gcs_transcript_uri,

    -- Competitors mentioned for this feedback (comma-separated)
    (
        SELECT string_agg(DISTINCT c.competitor_name, ', ' ORDER BY c.competitor_name)
        FROM feedback_competitors c
        WHERE c.feedback_id = f.id
    )                                                 AS competitors_mentioned,

    -- File / geo context for filters
    fd.file_name,
    fd.call_date,
    fd.language_code,
    fd.state,
    fd.division,
    fd.zone,
    fd.cluster,
    fd.rfmm_cluster,
    fd.town_city,
    fd.fme_code,
    fd.user_type,
    fd.data_source,

    j.status                                          AS job_status,
    j.gcs_input_uri                                   AS audio_gcs_uri
FROM feedbacks f
JOIN jobs j
  ON j.id = f.job_id
LEFT JOIN products p
  ON p.id = f.product_id
LEFT JOIN processed_file pf
  ON pf.job_id = f.job_id
LEFT JOIN file_details fd
  ON fd.job_id = f.job_id
LEFT JOIN feedback_tag_link l
  ON l.feedback_id = f.id
LEFT JOIN feedback_tags t
  -- Local/ORM: feedback_tags.id (uuid). Cloud SQL: feedback_tags.tag_id (int).
  -- scripts/apply_pbi_views.py rewrites this join when tag_id is the PK.
  ON t.id = l.tag_id;

COMMENT ON VIEW vw_pbi_feedback_fact IS
  'Power BI fact: one row per feedback×tag. Use for detail reports (AI summary, excerpt, full conversation) and as source for measures.';

-- Slim grain for dashboard aggregations: same joins as the fact view except
-- processed_file (transcripts). COUNT/GROUP BY must not scan million-row blobs.
CREATE OR REPLACE VIEW vw_pbi_feedback_fact_slim AS
SELECT
    f.id                                              AS feedback_id,
    f.job_id,
    f.created_at                                      AS feedback_created_at,
    COALESCE(NULLIF(TRIM(t.group_type), ''), NULLIF(TRIM(f.group_type), ''), 'UNKNOWN')
                                                      AS feedback_group,
    COALESCE(NULLIF(TRIM(t.category), ''), NULLIF(TRIM(f.category_type), ''), 'UNKNOWN')
                                                      AS feedback_category,
    COALESCE(NULLIF(TRIM(t.tag_name), ''), '(untagged)')
                                                      AS feedback_tag,
    NULLIF(TRIM(t.sub_tag_name), '')                  AS feedback_sub_tag,
    COALESCE(NULLIF(TRIM(f.product_name), ''), p.product_name)
                                                      AS product_name,
    f.product_id,
    p.short_code                                      AS product_short_code,
    f.ai_summary                                      AS feedback_summary_ai,
    f.verbatim_quote                                  AS feedback_excerpt,
    (
        SELECT string_agg(DISTINCT c.competitor_name, ', ' ORDER BY c.competitor_name)
        FROM feedback_competitors c
        WHERE c.feedback_id = f.id
    )                                                 AS competitors_mentioned,
    fd.file_name,
    fd.call_date,
    fd.language_code,
    fd.state,
    fd.division,
    fd.zone,
    fd.cluster,
    fd.rfmm_cluster,
    fd.town_city,
    fd.fme_code,
    fd.user_type,
    fd.data_source,
    j.status                                          AS job_status,
    j.gcs_input_uri                                   AS audio_gcs_uri
FROM feedbacks f
JOIN jobs j
  ON j.id = f.job_id
LEFT JOIN products p
  ON p.id = f.product_id
LEFT JOIN file_details fd
  ON fd.job_id = f.job_id
LEFT JOIN feedback_tag_link l
  ON l.feedback_id = f.id
LEFT JOIN feedback_tags t
  ON t.id = l.tag_id;

COMMENT ON VIEW vw_pbi_feedback_fact_slim IS
  'Dashboard fact without transcripts. Use for summary, product drill, and paginated detail.';

-- ── Aggregated counts (group / category / tag / sub-tag / product) ───────────
CREATE OR REPLACE VIEW vw_pbi_feedback_counts AS
SELECT
    feedback_group,
    feedback_category,
    feedback_tag,
    feedback_sub_tag,
    product_name,
    COUNT(DISTINCT feedback_id) AS feedback_count
FROM vw_pbi_feedback_fact
GROUP BY
    feedback_group,
    feedback_category,
    feedback_tag,
    feedback_sub_tag,
    product_name;

COMMENT ON VIEW vw_pbi_feedback_counts IS
  'Power BI: counts by group, category, tag, sub-tag, product. Let Power BI compute product/category totals.';

-- ── Tag-level counts (no product) — USER / DEALER / PDT rollups ─────────────
CREATE OR REPLACE VIEW vw_pbi_tag_counts AS
SELECT
    feedback_group,
    feedback_category,
    feedback_tag,
    feedback_sub_tag,
    COUNT(DISTINCT feedback_id) AS feedback_count
FROM vw_pbi_feedback_fact
GROUP BY
    feedback_group,
    feedback_category,
    feedback_tag,
    feedback_sub_tag;

COMMENT ON VIEW vw_pbi_tag_counts IS
  'Power BI: counts by group/category/tag/sub-tag (no product). Matches USER GROUP / DEALER GROUP tag matrices.';

-- ── PDT by product (report: Group | Product | Category | Tag | Count) ───────
CREATE OR REPLACE VIEW vw_pbi_pdt_product_counts AS
SELECT
    feedback_group,
    product_name,
    feedback_category,
    feedback_tag,
    feedback_sub_tag,
    COUNT(DISTINCT feedback_id) AS feedback_count
FROM vw_pbi_feedback_fact
WHERE feedback_group = 'PDT GROUP'
GROUP BY
    feedback_group,
    product_name,
    feedback_category,
    feedback_tag,
    feedback_sub_tag;

COMMENT ON VIEW vw_pbi_pdt_product_counts IS
  'Power BI PDT report: counts by product × category × tag. Filter product_name IS NOT NULL for product-specific rows.';

-- ── Taxonomy coverage (all tags with counts, including zeros) ───────────────
CREATE OR REPLACE VIEW vw_pbi_taxonomy_coverage AS
SELECT
    tax.tag_id,
    tax.feedback_group,
    tax.feedback_category,
    tax.feedback_tag,
    tax.feedback_sub_tag,
    tax.description                                   AS tag_description,
    COALESCE(cnt.feedback_count, 0)                   AS feedback_count
FROM bi_feedback_taxonomy tax
LEFT JOIN (
    SELECT
        feedback_group,
        feedback_category,
        feedback_tag,
        feedback_sub_tag,
        COUNT(DISTINCT feedback_id) AS feedback_count
    FROM vw_pbi_feedback_fact
    GROUP BY feedback_group, feedback_category, feedback_tag, feedback_sub_tag
) cnt
  ON cnt.feedback_group = tax.feedback_group
 AND cnt.feedback_category = tax.feedback_category
 AND (
        -- Normal tags: taxonomy.feedback_tag matches stored tag_name
        lower(cnt.feedback_tag) = lower(tax.feedback_tag)
        -- Marine-style taxonomy rows store the leaf label in feedback_sub_tag
        OR (
            tax.feedback_sub_tag IS NOT NULL
            AND lower(cnt.feedback_tag) = lower(tax.feedback_sub_tag)
        )
     );

COMMENT ON VIEW vw_pbi_taxonomy_coverage IS
  'Power BI: full taxonomy with feedback_count (0 when none). Matches empty count matrices in report templates.';

-- ── Detail report (AI summary + excerpt + full conversation) ────────────────
CREATE OR REPLACE VIEW vw_pbi_feedback_detail AS
SELECT
    feedback_group,
    feedback_category,
    feedback_tag,
    feedback_sub_tag,
    product_name,
    competitors_mentioned,
    feedback_summary_ai,
    feedback_excerpt,
    full_conversation,
    audio_gcs_uri,
    gcs_transcript_uri,
    call_date,
    division,
    zone,
    state,
    data_source,
    feedback_id,
    job_id
FROM vw_pbi_feedback_fact;

COMMENT ON VIEW vw_pbi_feedback_detail IS
  'Power BI detail tabs: category/tag + AI summary + verbatim excerpt + full conversation.';

-- ── Convenience filters per feedback group ──────────────────────────────────
CREATE OR REPLACE VIEW vw_pbi_pdt_detail AS
SELECT * FROM vw_pbi_feedback_detail WHERE feedback_group = 'PDT GROUP';

CREATE OR REPLACE VIEW vw_pbi_user_detail AS
SELECT * FROM vw_pbi_feedback_detail WHERE feedback_group = 'USER GROUP';

CREATE OR REPLACE VIEW vw_pbi_dealer_detail AS
SELECT * FROM vw_pbi_feedback_detail WHERE feedback_group = 'DEALER GROUP';

CREATE OR REPLACE VIEW vw_pbi_pdt_tag_counts AS
SELECT * FROM vw_pbi_tag_counts WHERE feedback_group = 'PDT GROUP';

CREATE OR REPLACE VIEW vw_pbi_user_tag_counts AS
SELECT * FROM vw_pbi_tag_counts WHERE feedback_group = 'USER GROUP';

CREATE OR REPLACE VIEW vw_pbi_dealer_tag_counts AS
SELECT * FROM vw_pbi_tag_counts WHERE feedback_group = 'DEALER GROUP';

COMMIT;
