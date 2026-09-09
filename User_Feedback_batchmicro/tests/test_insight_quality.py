from unittest.mock import patch

from services.shared.insight_quality import (
    TAG_PACKAGING_COMPLAINT,
    TAG_PERFORMANCE_IMPROVEMENTS,
    dedupe_cloned_insights,
    filter_meaningful_insights,
    is_actionable_feedback,
    is_user_feedback,
    tag_justifies_text,
)
from services.shared.vertex_ai import clip_verbatim_quote_to_one_speaker, generate_insights


def test_drops_usage_quantity_without_quality_claim():
    item = {
        "summary": "The user confirmed that at least 25 kg of Fevicol MARINE has been used.",
        "verbatim_quote": "Yes, at least 25 kg of Fevicol MARINE has been used here.",
        "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        "product_name": "Fevicol MARINE",
    }
    assert is_actionable_feedback(item) is False


def test_keeps_short_user_praise_as_performance():
    item = {
        "summary": "User found Fevicol X-Per to be excellent and superb.",
        "verbatim_quote": "Excellent, superb.",
        "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        "product_name": "Fevicol X-Per",
    }
    assert is_user_feedback(item) is True
    assert is_actionable_feedback(item) is True
    assert tag_justifies_text(item) is True


def test_keeps_coverage_as_performance_feedback():
    item = {
        "summary": "Everyone asks for Fevicol MARINE due to its good coverage.",
        "verbatim_quote": "Yes, the coverage is also very good in this.",
        "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        "product_name": "Fevicol MARINE",
    }
    assert is_actionable_feedback(item) is True
    assert tag_justifies_text(item) is True


def test_feedback_must_be_user_not_fme():
    fme = {
        "summary": "The FME explained that the scheme offers one bonus point per 300 kg.",
        "verbatim_quote": "300 kg per kilo, one bonus point will come separately.",
        "tag_ids": [22],
    }
    user = {
        "summary": "The user asks why the bonus is not coming despite a long association.",
        "verbatim_quote": "Sir, why isn't it coming?",
        "tag_ids": [22],
    }
    assert is_user_feedback(fme) is False
    assert is_user_feedback(user) is True


def test_clip_drops_fme_only_quote():
    assert clip_verbatim_quote_to_one_speaker(
        "FME: Sir, a new product has come, Fevicol X-Per."
    ) == ""
    assert clip_verbatim_quote_to_one_speaker(
        "FME: How was Hyper Star?\nUser: It's better, no bubbling."
    ) == "It's better, no bubbling."


def test_drops_fme_product_pitch():
    item = {
        "summary": "The FME introduced Fevicol X-Per as a new product.",
        "verbatim_quote": "Sir, a new product has come, Fevicol X-Per.",
        "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        "product_name": "Fevicol X-Per",
    }
    assert is_actionable_feedback(item) is False


def test_drops_packaging_tag_on_century_plywood_usage():
    item = {
        "summary": "The user is using Century plywood as per customer requirement.",
        "verbatim_quote": "They use Century as per the customer's requirement.",
        "tag_ids": [TAG_PACKAGING_COMPLAINT],
        "product_name": "Century",
    }
    assert tag_justifies_text(item) is False


def test_keeps_set_time_and_ease_as_performance():
    item = {
        "summary": "The user likes Fevicol Multilock because it makes sticking acrylic sheets easy, sets in 2-3 minutes.",
        "verbatim_quote": "It sets in two three minutes and sticking is easy.",
        "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        "product_name": "Fevicol Multilock",
    }
    assert is_actionable_feedback(item) is True
    assert tag_justifies_text(item) is True


def test_keeps_missing_applicator_as_packaging():
    item = {
        "summary": "The user ordered Fevicol Multilock but the comb applicator was not sent with the pack.",
        "verbatim_quote": "The comb applicator was not sent with it.",
        "tag_ids": [TAG_PACKAGING_COMPLAINT],
        "product_name": "Fevicol Multilock",
    }
    assert is_actionable_feedback(item) is True
    assert tag_justifies_text(item) is True


def test_keeps_packaging_leak():
    item = {
        "summary": "Marine tin leaked from the lid on the last lot.",
        "verbatim_quote": "The packets are leaking from the sides.",
        "tag_ids": [TAG_PACKAGING_COMPLAINT],
        "product_name": "Fevicol Marine",
    }
    assert is_actionable_feedback(item) is True
    assert tag_justifies_text(item) is True


def test_dedupes_cloned_summary_across_skus():
    summary = (
        "The user initially used Fevicol SH, then switched to Fevicol MARINE "
        "which they liked, and is now using Fevicol HI-PER STAR which they also like."
    )
    quote = "Initially, I was using Fevicol SH. Then Fevicol MARINE came."
    rows = [
        {
            "summary": summary,
            "verbatim_quote": quote,
            "product_name": name,
            "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
        }
        for name in ("Fevicol SH", "Fevicol MARINE", "Fevicol HI-PER STAR")
    ]
    kept = dedupe_cloned_insights(rows)
    assert len(kept) == 1
    assert kept[0]["product_name"] == "Fevicol SH"


def test_filter_meaningful_insights_drops_dump_bin_and_clones():
    kept = filter_meaningful_insights(
        [
            {
                "summary": "The user applied 20 kg of Fevicol HI-PER STAR.",
                "verbatim_quote": "I used Fevicol HI-PER STAR last time, 20 kg.",
                "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
                "product_name": "Fevicol HI-PER STAR",
            },
            {
                "summary": "Marine pack leaked from the lid.",
                "verbatim_quote": "The tin was leaking.",
                "tag_ids": [TAG_PACKAGING_COMPLAINT],
                "product_name": "Fevicol Marine",
            },
        ]
    )
    assert len(kept) == 1
    assert "leaked" in kept[0]["summary"]


def test_generate_insights_applies_quality_filter():
    raw = [
        {
            "insight_focus": "product",
            "summary": "User used 25 kg Marine.",
            "verbatim_quote": "25 kg used.",
            "competitors_mentioned": [],
        }
    ]
    tagged = [
        {
            "group_type": "PDT GROUP",
            "category_type": "Product",
            "tag_ids": [TAG_PERFORMANCE_IMPROVEMENTS],
            "verbatim_quote": "25 kg used.",
            "summary": "User used 25 kg Marine.",
            "product_name": "Fevicol Marine",
            "competitors_mentioned": [],
        },
        {
            "group_type": "PDT GROUP",
            "category_type": "Product",
            "tag_ids": [TAG_PACKAGING_COMPLAINT],
            "verbatim_quote": "The packets are leaking from the sides.",
            "summary": "Customer reports Fevicol SH packaging leakage.",
            "product_name": "Fevicol SH",
            "competitors_mentioned": [],
        },
    ]
    with patch(
        "services.shared.vertex_ai._extract_raw_insights",
        return_value=(raw, {"input": 1, "output": 1, "total": 2}),
    ), patch(
        "services.shared.vertex_ai._categorize_insights",
        return_value=(tagged, {"input": 1, "output": 1, "total": 2}),
    ):
        insights, _tokens = generate_insights("transcript", "1|Fevicol SH", "")

    assert len(insights) == 1
    assert "leakage" in insights[0]["summary"].lower()
