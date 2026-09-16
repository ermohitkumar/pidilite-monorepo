from datetime import date, datetime, timezone

from sqlalchemy import text

from db.models import Feedback, FeedbackTag, FileDetails, Job
from services.period_summarize.compact import gather_insights, list_tag_keys


def _try_sql(db, sql, params=None):
    try:
        db.execute(text(sql), params or {})
        db.commit()
    except Exception:
        db.rollback()


def _prepare_insight_schema(db):
    _try_sql(db, "ALTER TABLE feedbacks ADD COLUMN product_name TEXT")
    _try_sql(db, "ALTER TABLE feedbacks ADD COLUMN group_type TEXT")
    _try_sql(db, "ALTER TABLE feedbacks ADD COLUMN ai_summary TEXT")
    _try_sql(db, "ALTER TABLE feedback_tags ADD COLUMN tag_id INTEGER")
    _try_sql(
        db,
        """
        CREATE TABLE IF NOT EXISTS feedback_tag_link (
            feedback_id VARCHAR(36) NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (feedback_id, tag_id)
        )
        """,
    )


def _insert_insight(db, *, product_name, group_type, summary, tag_ids, call_date):
    job = Job(gcs_input_uri="gs://test-bucket/call.wav")
    db.add(job)
    db.flush()
    db.add(FileDetails(
        job_id=job.id,
        file_name="call.wav",
        call_date=call_date,
        fme_code="BDDEL03",
    ))
    feedback = Feedback(job_id=job.id, verbatim_quote="quote", remarks="remark")
    db.add(feedback)
    db.flush()
    stored_feedback_id = db.execute(text("SELECT id FROM feedbacks ORDER BY rowid DESC LIMIT 1")).scalar()
    db.execute(
        text(
            "UPDATE feedbacks SET product_name=:product_name, group_type=:group_type, "
            "ai_summary=:ai_summary, created_at=:created_at WHERE id=:id"
        ),
        {
            "product_name": product_name,
            "group_type": group_type,
            "ai_summary": summary,
            "created_at": call_date.replace(tzinfo=None).isoformat(sep=" "),
            "id": stored_feedback_id,
        },
    )
    for tag_id, tag_name in tag_ids:
        existing = db.execute(
            text("SELECT tag_id FROM feedback_tags WHERE tag_id = :tag_id"),
            {"tag_id": tag_id},
        ).first()
        if not existing:
            tag = FeedbackTag(tag_name=tag_name)
            db.add(tag)
            db.flush()
            stored_tag_id = db.execute(
                text("SELECT id FROM feedback_tags ORDER BY rowid DESC LIMIT 1")
            ).scalar()
            db.execute(
                text("UPDATE feedback_tags SET tag_id = :tag_id WHERE id = :id"),
                {"tag_id": tag_id, "id": stored_tag_id},
            )
        db.execute(
            text("INSERT INTO feedback_tag_link (feedback_id, tag_id) VALUES (:feedback_id, :tag_id)"),
            {"feedback_id": stored_feedback_id, "tag_id": tag_id},
        )
    db.commit()
    return stored_feedback_id


def test_gather_insights_tag_only_returns_linked_rows(db_session):
    _prepare_insight_schema(db_session)
    call_date = datetime(2026, 9, 10, tzinfo=timezone.utc)
    shared = _insert_insight(
        db_session,
        product_name="Marine",
        group_type="PDT GROUP",
        summary="Cap leaks on Marine tins",
        tag_ids=[(22, "Packaging"), (6, "Existing Product - Performance improvements")],
        call_date=call_date,
    )
    _insert_insight(
        db_session,
        product_name="SH",
        group_type="PDT GROUP",
        summary="Open time is short",
        tag_ids=[(6, "Existing Product - Performance improvements")],
        call_date=call_date,
    )
    _insert_insight(
        db_session,
        product_name=None,
        group_type="USER GROUP",
        summary="Queue was long at the meet",
        tag_ids=[(30, "User meet - long queues")],
        call_date=call_date,
    )

    packaging = gather_insights(
        db_session, start=date(2026, 9, 1), end=date(2026, 9, 30), grain="tag", grain_key="22",
    )
    performance = gather_insights(
        db_session, start=date(2026, 9, 1), end=date(2026, 9, 30), grain="tag", grain_key="6",
    )
    queues = gather_insights(
        db_session, start=date(2026, 9, 1), end=date(2026, 9, 30), grain="tag", grain_key="30",
    )

    assert len(packaging) == 1
    assert packaging[0]["ai_summary"] == "Cap leaks on Marine tins"
    assert {row["ai_summary"] for row in performance} == {
        "Cap leaks on Marine tins",
        "Open time is short",
    }
    assert len(queues) == 1
    assert queues[0]["product_name"] in {None, ""}
    assert queues[0]["ai_summary"] == "Queue was long at the meet"
    assert shared

    cube = gather_insights(
        db_session,
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        grain="bde_pt",
        grain_key="BDDEL03::PDT::Marine::22",
    )
    assert len(cube) == 1
    assert cube[0]["ai_summary"] == "Cap leaks on Marine tins"
    user_tag = gather_insights(
        db_session,
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        grain="bde_t",
        grain_key="BDDEL03::USER::30",
    )
    assert len(user_tag) == 1
    assert user_tag[0]["ai_summary"] == "Queue was long at the meet"


def test_list_tag_keys_returns_distinct_ids_in_period(db_session):
    _prepare_insight_schema(db_session)
    call_date = datetime(2026, 9, 12, tzinfo=timezone.utc)
    _insert_insight(
        db_session,
        product_name="Marine",
        group_type="PDT GROUP",
        summary="Leak",
        tag_ids=[(22, "Packaging"), (6, "Existing Product - Performance improvements")],
        call_date=call_date,
    )
    keys = list_tag_keys(db_session, date(2026, 9, 1), date(2026, 9, 30))
    assert {item["grain_key"] for item in keys} == {"6", "22"}
    labels = {item["grain_key"]: item["grain_label"] for item in keys}
    assert labels["22"] == "Packaging"
    assert list_tag_keys(db_session, date(2026, 8, 1), date(2026, 8, 31)) == []
