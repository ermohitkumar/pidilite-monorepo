from unittest.mock import patch

from services.shared.vertex_ai import _categorize_insights, _extract_raw_insights


def test_extraction_prompt_does_not_treat_site_recording_as_user_focus():
    with patch("services.shared.vertex_ai._rest_generate_content") as mock:
        mock.return_value = ({"insights": []}, {"input": 1, "output": 1, "total": 2})
        _extract_raw_insights("hello")

    system = mock.call_args.args[0]
    assert 'Do NOT create a "user" insight merely because the FME is recording on a site' in system
    assert "Product talk on a site is still \"product\", not \"user\"" in system
    assert "Extract even brief usage" not in system
    assert "DO NOT EXTRACT" in system
    assert "FEEDBACK IS ALWAYS THE USER'S ANSWER" in system
    assert "site visits, loyalty" not in system


def test_categorize_prompt_omits_unmatched_and_restricts_site_visits():
    with patch("services.shared.vertex_ai._rest_generate_content") as mock:
        mock.return_value = ({"insights": []}, {"input": 1, "output": 1, "total": 2})
        _categorize_insights(
            [{"insight_focus": "user", "summary": "used XP on ply"}],
            "SKU|Product_Name",
            "[USER GROUP]:\n  - [tag_id=17] Site visits",
        )

    system = mock.call_args.args[0]
    assert "MUST assign at least one tag_id" not in system
    assert "OMIT that insight from the output array entirely" in system
    assert "NEVER because the audio was recorded on a job site" in system
    assert "reclassify to PDT GROUP with PDT tags" in system
    assert "CATCH-ALL BANS" in system
    assert "SUMMARY MUST JUSTIFY THE TAG" in system


def test_categorize_drops_insights_with_empty_tag_ids():
    with patch("services.shared.vertex_ai._rest_generate_content") as mock:
        mock.return_value = (
            {
                "insights": [
                    {
                        "group_type": "USER GROUP",
                        "category_type": "User Engagement",
                        "tag_ids": [],
                        "verbatim_quote": "We used XP",
                        "summary": "User used XP",
                        "competitors_mentioned": [],
                    },
                    {
                        "group_type": "USER GROUP",
                        "category_type": "User Meets",
                        "tag_ids": [24],
                        "verbatim_quote": "FCC meet was good",
                        "summary": "User liked FCC meet",
                        "competitors_mentioned": [],
                    },
                ]
            },
            {"input": 1, "output": 1, "total": 2},
        )
        insights, _tokens = _categorize_insights(
            [{"insight_focus": "user"}],
            "SKU|Product_Name",
            "[USER GROUP]:",
        )

    assert len(insights) == 1
    assert insights[0]["tag_ids"] == [24]
