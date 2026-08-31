"""CRUD for products and feedback_tags master tables."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import MetaData, Table, delete, inspect as sa_inspect, select, update
from sqlalchemy.orm import Session

from core.dependencies import RoleChecker
from core.exceptions import APIException
from core.permissions import Permissions
from core.response import make_response
from db.session import get_db

logger = logging.getLogger(__name__)

read_access = Depends(RoleChecker(Permissions.VIEW_DASHBOARD))
write_access = Depends(RoleChecker(Permissions.MANAGE_REGISTRY))
DbSession = Annotated[Session, Depends(get_db)]

products_router = APIRouter(prefix="/products", tags=["Catalog — Products"])
tags_router = APIRouter(prefix="/feedback-tags", tags=["Catalog — Tags"])


class ProductCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=200)
    short_code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = True


class ProductUpdate(BaseModel):
    product_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    short_code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class TagCreate(BaseModel):
    tag_id: Optional[int] = Field(default=None, ge=1)
    tag_name: str = Field(min_length=1, max_length=200)
    sub_tag_name: Optional[str] = Field(default=None, max_length=200)
    group_type: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    is_active: bool = True


class TagUpdate(BaseModel):
    tag_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    sub_tag_name: Optional[str] = Field(default=None, max_length=200)
    group_type: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _table(db: Session, name: str) -> Table:
    metadata = MetaData()
    return Table(name, metadata, autoload_with=db.get_bind())


def _columns(db: Session, name: str) -> set[str]:
    return {col["name"] for col in sa_inspect(db.get_bind()).get_columns(name)}


def _row_dict(row: Any) -> dict:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    if hasattr(row, "_asdict"):
        return row._asdict()
    return dict(row)


def _filter_payload(payload: dict, columns: set[str]) -> dict:
    return {key: value for key, value in payload.items() if key in columns and value is not None}


def _needs_client_id(table: Table) -> bool:
    col = table.c.id
    type_name = str(col.type).upper()
    return "CHAR" in type_name or "UUID" in type_name or "VARCHAR" in type_name


def _pk_column(table: Table):
    return list(table.primary_key.columns)[0]


def _serialize(row: dict) -> dict:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    if out.get("id") is not None:
        out["id"] = str(out["id"])
    elif out.get("tag_id") is not None:
        out["id"] = str(out["tag_id"])
    return out


def _insert_and_fetch(db: Session, table: Table, values: dict):
    result = db.execute(table.insert().values(**values))
    inserted = result.inserted_primary_key[0] if result.inserted_primary_key else None
    result.close()
    db.flush()
    pk = _pk_column(table)
    lookup = inserted if inserted is not None else values.get(pk.name)
    if lookup is not None:
        row = db.execute(select(table).where(pk == lookup)).first()
    else:
        row = db.execute(select(table).order_by(pk.desc())).first()
    db.commit()
    return row


def _tag_pk(columns: set[str]) -> str:
    return "tag_id" if "tag_id" in columns else "id"


def _coerce_pk(pk_col, raw_id: str):
    try:
        if "INT" in str(pk_col.type).upper():
            return int(raw_id)
    except (TypeError, ValueError):
        pass
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return raw_id


@products_router.get("/", dependencies=[read_access])
def list_products(
    db: DbSession,
    q: Annotated[Optional[str], Query()] = None,
    active_only: bool = False,
):
    try:
        table = _table(db, "products")
        stmt = select(table)
        if active_only and "is_active" in table.c:
            stmt = stmt.where(table.c.is_active.is_(True))
        if q and "product_name" in table.c:
            stmt = stmt.where(table.c.product_name.ilike(f"%{q}%"))
        order_col = table.c.product_name if "product_name" in table.c else list(table.c)[0]
        rows = [_serialize(_row_dict(row)) for row in db.execute(stmt.order_by(order_col)).fetchall()]
        return make_response(success=True, message="Products retrieved successfully", data=rows)
    except APIException:
        raise
    except Exception as exc:
        logger.exception("Failed to list products")
        raise APIException(status_code=500, message="Failed to list products", error=str(exc))


@products_router.post("/", dependencies=[write_access])
def create_product(payload: ProductCreate, db: DbSession):
    try:
        table = _table(db, "products")
        columns = _columns(db, "products")
        values = _filter_payload(payload.model_dump(), columns)
        if "product_name" not in values:
            raise APIException(status_code=400, message="product_name is required", error="ValidationError")
        if "id" in columns and "id" not in values and _needs_client_id(table):
            values["id"] = str(uuid.uuid4())
        existing = db.execute(
            select(table).where(table.c.product_name == values["product_name"])
        ).first()
        if existing:
            raise APIException(status_code=409, message="Product name already exists", error="Conflict")
        row = _insert_and_fetch(db, table, values)
        if row is None:
            raise APIException(status_code=500, message="Product created but could not be loaded", error="InsertError")
        return make_response(success=True, message="Product created", data=_serialize(_row_dict(row)))
    except APIException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create product")
        raise APIException(status_code=500, message="Failed to create product", error=str(exc))


@products_router.put("/{product_id}", dependencies=[write_access])
def update_product(product_id: str, payload: ProductUpdate, db: DbSession):
    try:
        table = _table(db, "products")
        columns = _columns(db, "products")
        values = _filter_payload(payload.model_dump(exclude_unset=True), columns)
        if not values:
            raise APIException(status_code=400, message="No fields to update", error="ValidationError")
        pk = table.c.id
        lookup = _coerce_pk(pk, product_id)
        result = db.execute(update(table).where(pk == lookup).values(**values))
        result.close()
        db.flush()
        row = db.execute(select(table).where(pk == lookup)).first()
        if row is None:
            raise APIException(status_code=404, message="Product not found", error="NotFound")
        db.commit()
        return make_response(success=True, message="Product updated", data=_serialize(_row_dict(row)))
    except APIException:
        db.rollback()
        raise
    except Exception as extra:
        db.rollback()
        logger.exception("Failed to update product")
        raise APIException(status_code=500, message="Failed to update product", error=str(extra))


@products_router.delete("/{product_id}", dependencies=[write_access])
def delete_product(product_id: str, db: DbSession):
    try:
        table = _table(db, "products")
        pk = table.c.id
        lookup = _coerce_pk(pk, product_id)
        row = db.execute(select(table).where(pk == lookup)).first()
        if row is None:
            raise APIException(status_code=404, message="Product not found", error="NotFound")
        db.execute(delete(table).where(pk == lookup))
        db.commit()
        return make_response(success=True, message="Product deleted", data={"id": str(lookup)})
    except APIException:
        db.rollback()
        raise
    except Exception as extra:
        db.rollback()
        logger.exception("Failed to delete product")
        raise APIException(
            status_code=409,
            message="Cannot delete product while feedback rows still reference it. Deactivate it instead.",
            error=str(extra),
        )


@tags_router.get("/", dependencies=[read_access])
def list_tags(
    db: DbSession,
    q: Annotated[Optional[str], Query()] = None,
    group_type: Annotated[Optional[str], Query()] = None,
):
    try:
        table = _table(db, "feedback_tags")
        stmt = select(table)
        if q and "tag_name" in table.c:
            stmt = stmt.where(table.c.tag_name.ilike(f"%{q}%"))
        if group_type and "group_type" in table.c:
            stmt = stmt.where(table.c.group_type == group_type)
        pk = table.c[_tag_pk(set(table.c.keys()))]
        rows = [_serialize(_row_dict(row)) for row in db.execute(stmt.order_by(pk)).fetchall()]
        return make_response(success=True, message="Tags retrieved successfully", data=rows)
    except Exception as extra:
        logger.exception("Failed to list tags")
        raise APIException(status_code=500, message="Failed to list tags", error=str(extra))


@tags_router.post("/", dependencies=[write_access])
def create_tag(payload: TagCreate, db: DbSession):
    try:
        table = _table(db, "feedback_tags")
        columns = _columns(db, "feedback_tags")
        values = _filter_payload(payload.model_dump(), columns)
        pk_name = _tag_pk(columns)
        if pk_name == "tag_id" and not values.get("tag_id"):
            max_id = [row[0] for row in db.execute(select(table.c.tag_id)).fetchall() if row[0] is not None]
            values["tag_id"] = (max(max_id) + 1) if max_id else 1
        if pk_name == "id" and "id" not in values:
            values["id"] = str(uuid.uuid4())
        row = _insert_and_fetch(db, table, values)
        if row is None:
            raise APIException(status_code=500, message="Tag created but could not be loaded", error="InsertError")
        return make_response(success=True, message="Tag created", data=_serialize(_row_dict(row)))
    except APIException:
        db.rollback()
        raise
    except Exception as extra:
        db.rollback()
        logger.exception("Failed to create tag")
        raise APIException(status_code=500, message="Failed to create tag", error=str(extra))


@tags_router.put("/{tag_id}", dependencies=[write_access])
def update_tag(tag_id: str, payload: TagUpdate, db: DbSession):
    try:
        table = _table(db, "feedback_tags")
        columns = _columns(db, "feedback_tags")
        values = _filter_payload(payload.model_dump(exclude_unset=True), columns)
        if not values:
            raise APIException(status_code=400, message="No fields to update", error="ValidationError")
        pk_name = _tag_pk(columns)
        pk = table.c[pk_name]
        lookup = _coerce_pk(pk, tag_id)
        result = db.execute(update(table).where(pk == lookup).values(**values))
        result.close()
        db.flush()
        row = db.execute(select(table).where(pk == lookup)).first()
        if row is None:
            raise APIException(status_code=404, message="Tag not found", error="NotFound")
        db.commit()
        return make_response(success=True, message="Tag updated", data=_serialize(_row_dict(row)))
    except APIException:
        db.rollback()
        raise
    except Exception as extra:
        db.rollback()
        logger.exception("Failed to update tag")
        raise APIException(status_code=500, message="Failed to update tag", error=str(extra))


@tags_router.delete("/{tag_id}", dependencies=[write_access])
def delete_tag(tag_id: str, db: DbSession):
    try:
        table = _table(db, "feedback_tags")
        columns = _columns(db, "feedback_tags")
        pk_name = _tag_pk(columns)
        pk = table.c[pk_name]
        lookup = _coerce_pk(pk, tag_id)
        row = db.execute(select(table).where(pk == lookup)).first()
        if row is None:
            raise APIException(status_code=404, message="Tag not found", error="NotFound")
        link_cols = _columns(db, "feedback_tag_link") if "feedback_tag_link" in sa_inspect(db.get_bind()).get_table_names() else set()
        if "tag_id" in link_cols:
            links = _table(db, "feedback_tag_link")
            db.execute(delete(links).where(links.c.tag_id == lookup))
        db.execute(delete(table).where(pk == lookup))
        db.commit()
        return make_response(success=True, message="Tag deleted", data={pk_name: lookup})
    except APIException:
        db.rollback()
        raise
    except Exception as extra:
        db.rollback()
        logger.exception("Failed to delete tag")
        raise APIException(status_code=500, message="Failed to delete tag", error=str(extra))
