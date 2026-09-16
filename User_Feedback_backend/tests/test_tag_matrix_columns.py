from pathlib import Path


FRONTEND_REPORTS = Path(__file__).resolve().parents[2] / "User-Feedback" / "lib" / "reports"


def test_overview_columns_include_ai_summary():
    text = (FRONTEND_REPORTS / "build.ts").read_text(encoding="utf-8")
    marker = "export function columnsForOverview()"
    assert marker in text
    body = text.split(marker, 1)[1].split("export function", 1)[0]
    assert '"feedback_summary_ai"' in body
    assert '"feedback_count"' in body


def test_tag_matrix_copies_ai_summary_onto_data_rows():
    text = (FRONTEND_REPORTS / "build.ts").read_text(encoding="utf-8")
    assert "summaryTagNarrative(" in text
    assert "feedback_summary_ai: narrative" in text
    assert "tax.feedback_category" in text
    assert "tax.feedback_tag" in text
    assert "Narrative is all India for this period" in (
        Path(__file__).resolve().parents[2]
        / "User-Feedback"
        / "components"
        / "reports"
        / "ReportsClient.tsx"
    ).read_text(encoding="utf-8")


def test_product_drill_includes_period_summaries_and_formatted_modal():
    root = Path(__file__).resolve().parents[2] / "User-Feedback"
    build = (FRONTEND_REPORTS / "build.ts").read_text(encoding="utf-8")
    marker = "export function columnsForProductDrill"
    body = build.split(marker, 1)[1].split("export function", 1)[0]
    assert '"feedback_summary_ai"' in body
    assert "periodProducts" in build
    reports = (root / "components" / "reports" / "ReportsClient.tsx").read_text(encoding="utf-8")
    assert "restrictToAvailable" in reports
    assert "FormattedSummary" in reports
    assert "periodProducts" in reports
    table = (root / "components" / "reports" / "ReportTable.tsx").read_text(encoding="utf-8")
    assert "View more" in table
    assert "line-clamp-3" in table
    drill = (root / "components" / "reports" / "ReportDrillView.tsx").read_text(encoding="utf-8")
    assert "wantProducts = !drill.product_name" in drill
    assert "showHeaderNarratives = !drill.product_name" in drill
    assert "Product summary" not in drill


def test_restrict_to_available_keeps_live_options_when_period_has_no_summaries():
    text = (FRONTEND_REPORTS / "period.ts").read_text(encoding="utf-8")
    body = text.split("export function restrictToAvailable", 1)[1].split("export function", 1)[0]
    assert "allowed.length === 0" in body
    assert "return live" in body


def test_tag_matrix_keeps_zero_count_taxonomy_rows():
    text = (FRONTEND_REPORTS / "build.ts").read_text(encoding="utf-8")
    body = text.split("export function buildTagMatrixFromSummary", 1)[1].split("export function", 1)[0]
    assert "else if (!count)" not in body
    assert "feedback_count: count" in body
