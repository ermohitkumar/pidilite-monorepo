from db.models import Product, FeedbackTag


def test_list_create_update_delete_product(client, db_session):
    db_session.add(Product(product_name="Fevicol SH", short_code="SH", is_active=True))
    db_session.commit()

    listed = client.get("/api/v1/products/")
    assert listed.status_code == 200
    names = [row["product_name"] for row in listed.json()["data"]]
    assert "Fevicol SH" in names

    created = client.post("/api/v1/products/", json={
        "product_name": "Fevicol EZEESPRAY",
        "short_code": "EZEE",
        "is_active": True,
    })
    assert created.status_code == 200
    product_id = created.json()["data"]["id"]

    updated = client.put(f"/api/v1/products/{product_id}", json={"short_code": "EZ"})
    assert updated.status_code == 200
    assert updated.json()["data"]["short_code"] == "EZ"

    deleted = client.delete(f"/api/v1/products/{product_id}")
    assert deleted.status_code == 200
    names_after = [row["product_name"] for row in client.get("/api/v1/products/").json()["data"]]
    assert "Fevicol EZEESPRAY" not in names_after


def test_duplicate_product_name_conflict(client, db_session):
    db_session.add(Product(product_name="Fevicol Marine", is_active=True))
    db_session.commit()
    resp = client.post("/api/v1/products/", json={"product_name": "Fevicol Marine"})
    assert resp.status_code == 409


def test_list_create_update_delete_tag(client, db_session):
    db_session.add(FeedbackTag(tag_name="Existing Product - Performance improvements", description="perf"))
    db_session.commit()

    listed = client.get("/api/v1/feedback-tags/")
    assert listed.status_code == 200
    assert listed.json()["data"]

    created = client.post("/api/v1/feedback-tags/", json={
        "tag_name": "Competition product",
        "group_type": "PDT GROUP",
        "category": "Competition",
        "description": "Competitor SKU mentioned",
    })
    assert created.status_code == 200
    tag_id = created.json()["data"]["id"]

    updated = client.put(f"/api/v1/feedback-tags/{tag_id}", json={"description": "Updated desc"})
    assert updated.status_code == 200
    assert updated.json()["data"]["description"] == "Updated desc"

    deleted = client.delete(f"/api/v1/feedback-tags/{tag_id}")
    assert deleted.status_code == 200
