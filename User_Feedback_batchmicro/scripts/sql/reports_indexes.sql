-- Indexes for dashboard report aggregations and paginated detail.
-- Safe to re-run. Apply on Cloud SQL / local Postgres:
--   psql ... -f scripts/sql/reports_indexes.sql

CREATE INDEX IF NOT EXISTS ix_feedbacks_job_id ON feedbacks (job_id);
CREATE INDEX IF NOT EXISTS ix_feedbacks_group_type ON feedbacks (group_type);
CREATE INDEX IF NOT EXISTS ix_feedbacks_category_type ON feedbacks (category_type);
CREATE INDEX IF NOT EXISTS ix_feedbacks_product_name ON feedbacks (product_name);
CREATE INDEX IF NOT EXISTS ix_feedbacks_created_at ON feedbacks (created_at);

CREATE INDEX IF NOT EXISTS ix_file_details_division ON file_details (division);
CREATE INDEX IF NOT EXISTS ix_file_details_zone ON file_details (zone);
CREATE INDEX IF NOT EXISTS ix_file_details_cluster ON file_details (cluster);
CREATE INDEX IF NOT EXISTS ix_file_details_data_source ON file_details (data_source);
CREATE INDEX IF NOT EXISTS ix_file_details_call_date ON file_details (call_date);

CREATE INDEX IF NOT EXISTS ix_feedback_tag_link_feedback_id ON feedback_tag_link (feedback_id);
CREATE INDEX IF NOT EXISTS ix_feedback_tag_link_tag_id ON feedback_tag_link (tag_id);

CREATE INDEX IF NOT EXISTS ix_feedback_tags_group_category_tag
    ON feedback_tags (group_type, category, tag_name);

CREATE INDEX IF NOT EXISTS ix_processed_file_job_id ON processed_file (job_id);
