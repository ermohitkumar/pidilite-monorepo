"""Apply the Library tag changes shipped with the application.

This runs once per PostgreSQL database during API startup. The frontend's
feedback_taxonomy.json remains the reporting taxonomy; this migration keeps the
database-backed Library Tags page in sync with the corresponding workbook edits.
"""
from __future__ import annotations

import uuid

from sqlalchemy import MetaData, Table, inspect, select, text


MIGRATION_ID = "library_feedback_tags_2026_11_v1"

NEW_TAGS = (
    (188, "Product Quality", "Overall Good product",
     "Positive overall feedback on the product under Product / Product Quality."),
    (189, "Product Quality", "Good grab",
     "Positive feedback on product grab under Product / Product Quality."),
    (190, "Product Quality", "Helping/ Enabling me to complete sites faster",
     "Product helps complete sites faster under Product / Product Quality."),
    (191, "Product Packaging", "Good packaging",
     "Positive feedback on packaging under Product / Product Packaging."),
    (192, "Post application feedback", "Easy to use",
     "Positive feedback on ease of use under Product / Post application feedback."),
)


def _new_id(column) -> str | None:
    type_name = str(column.type).upper()
    if "UUID" in type_name or "CHAR" in type_name or "VARCHAR" in type_name:
        return str(uuid.uuid4())
    return None


def _category_id(conn, categories: Table | None, name: str):
    if categories is None or "category_name" not in categories.c or "id" not in categories.c:
        return None
    category_id = conn.execute(
        select(categories.c.id).where(categories.c.category_name == name).limit(1)
    ).scalar_one_or_none()
    if category_id is not None:
        return category_id

    values = {"category_name": name}
    if "description" in categories.c:
        values["description"] = f"Feedback category: {name}."
    if "is_active" in categories.c:
        values["is_active"] = True
    generated_id = _new_id(categories.c.id)
    if generated_id:
        values["id"] = generated_id
    result = conn.execute(categories.insert().values(**values))
    if generated_id:
        return generated_id
    return result.inserted_primary_key[0] if result.inserted_primary_key else None


def apply_library_taxonomy(engine) -> None:
    """Rename existing labels and activate/insert the five workbook tags once."""
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("feedback_tags"):
        return

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS catalog_migrations (
                migration_id VARCHAR(200) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        already_applied = conn.execute(
            text("SELECT 1 FROM catalog_migrations WHERE migration_id = :id"),
            {"id": MIGRATION_ID},
        ).first()
        if already_applied:
            return

        # The API supports both the older ORM schema and the catalog schema.
        # Add the catalog columns when the local database was created from ORM models.
        for definition in (
            "tag_id INTEGER",
            "group_type VARCHAR(100)",
            "category VARCHAR(100)",
            "sub_tag_name VARCHAR(200)",
        ):
            conn.execute(text(
                f"ALTER TABLE feedback_tags ADD COLUMN IF NOT EXISTS {definition}"
            ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_tags_tag_id "
            "ON feedback_tags (tag_id) WHERE tag_id IS NOT NULL"
        ))

        metadata = MetaData()
        tags = Table("feedback_tags", metadata, autoload_with=conn)
        categories = None
        if inspect(conn).has_table("feedback_categories"):
            categories = Table("feedback_categories", metadata, autoload_with=conn)

        category_renames = {
            "Product Quality Complaint": "Product Quality",
            "Product Packaging Complaint": "Product Packaging",
        }
        if "category" in tags.c:
            for old_name, new_name in category_renames.items():
                conn.execute(
                    tags.update().where(tags.c.category == old_name).values(category=new_name)
                )
        if categories is not None and "category_name" in categories.c:
            for old_name, new_name in category_renames.items():
                conn.execute(categories.update().where(
                    categories.c.category_name == old_name
                ).values(category_name=new_name))

        if "tag_name" in tags.c:
            foul_query = tags.update().where(tags.c.tag_name == "Foul Odor").values(
                tag_name="Smell/ Odor"
            )
            conn.execute(foul_query)

        for tag_id, category, tag_name, description in NEW_TAGS:
            parent_id = _category_id(conn, categories, category)
            values = {}
            for column, value in (
                ("tag_id", tag_id),
                ("group_type", "Product"),
                ("category", category),
                ("tag_name", tag_name),
                ("description", description),
                ("is_active", True),
                ("category_id", parent_id),
            ):
                if column in tags.c and (value is not None or column != "category_id"):
                    values[column] = value

            existing = conn.execute(
                select(tags).where(tags.c.tag_id == tag_id).limit(1)
            ).first()
            if existing:
                conn.execute(tags.update().where(tags.c.tag_id == tag_id).values(**values))
            else:
                if "id" in tags.c:
                    generated_id = _new_id(tags.c.id)
                    if generated_id:
                        values["id"] = generated_id
                conn.execute(tags.insert().values(**values))

        conn.execute(
            text("INSERT INTO catalog_migrations (migration_id) VALUES (:id)"),
            {"id": MIGRATION_ID},
        )
