"""
Tests for the restocking recommendation and order-submission API endpoints.
"""
import re
from datetime import datetime

import pytest

# Only demand-forecast SKU with a matching inventory record in the fixture data
AFFORDABLE_SKU = "PSU-501"
AFFORDABLE_QUANTITY = 252
AFFORDABLE_UNIT_COST = 18.99
AFFORDABLE_LINE_COST = round(AFFORDABLE_QUANTITY * AFFORDABLE_UNIT_COST, 2)

# All other demand-forecast SKUs have no inventory record and must be excluded
EXCLUDED_SKUS = {
    "WDG-001", "BRG-102", "GSK-203", "MTR-304",
    "FLT-405", "VLV-506", "SNR-420", "CTL-330"
}


class TestRestockingRecommendationsEndpoint:
    """Test suite for GET /api/restocking/recommendations."""

    def test_get_recommendations_happy_path(self, client):
        """A generous budget should recommend and include the one affordable item."""
        response = client.get("/api/restocking/recommendations?budget=10000")
        assert response.status_code == 200

        data = response.json()
        assert data["budget"] == 10000
        assert isinstance(data["recommended_items"], list)

        affordable = next(
            (i for i in data["recommended_items"] if i["item_sku"] == AFFORDABLE_SKU), None
        )
        assert affordable is not None
        assert affordable["recommended_quantity"] == AFFORDABLE_QUANTITY
        assert affordable["unit_cost"] == AFFORDABLE_UNIT_COST
        assert affordable["line_cost"] == AFFORDABLE_LINE_COST
        assert affordable["included"] is True

        assert data["total_cost"] == AFFORDABLE_LINE_COST
        assert data["remaining_budget"] == round(10000 - AFFORDABLE_LINE_COST, 2)

    def test_get_recommendations_excludes_items_with_no_inventory_match(self, client):
        """Demand-forecast SKUs with no inventory record must be reported as excluded."""
        response = client.get("/api/restocking/recommendations?budget=10000")
        assert response.status_code == 200

        data = response.json()
        excluded_skus = {item["item_sku"] for item in data["excluded_items"]}
        assert excluded_skus == EXCLUDED_SKUS

        for item in data["excluded_items"]:
            assert item["reason"] == "no_inventory_match"

        # Excluded items must never leak into the recommended list
        recommended_skus = {item["item_sku"] for item in data["recommended_items"]}
        assert recommended_skus.isdisjoint(EXCLUDED_SKUS)

    def test_get_recommendations_budget_too_low(self, client):
        """A budget below the cheapest candidate leaves everything un-included."""
        response = client.get("/api/restocking/recommendations?budget=100")
        assert response.status_code == 200

        data = response.json()
        assert all(item["included"] is False for item in data["recommended_items"])
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 100

    def test_get_recommendations_zero_budget(self, client):
        """A zero budget is valid input, not an error, and selects nothing."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 0
        assert all(item["included"] is False for item in data["recommended_items"])

    def test_get_recommendations_negative_budget(self, client):
        """A negative budget is rejected with a 400 and an explanatory message."""
        response = client.get("/api/restocking/recommendations?budget=-1")
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_get_recommendations_missing_budget(self, client):
        """The budget query parameter is required."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422

    def test_recommendations_are_priority_ranked(self, client):
        """priority_rank should be assigned in ascending, gap-free order."""
        response = client.get("/api/restocking/recommendations?budget=10000")
        data = response.json()

        ranks = [item["priority_rank"] for item in data["recommended_items"]]
        assert ranks == sorted(ranks)
        assert ranks == list(range(1, len(ranks) + 1))


class TestCreateRestockingOrderEndpoint:
    """Test suite for POST /api/restocking-orders.

    These tests mutate the shared in-memory `orders` list, so they are kept
    last in the file and only ever assert deltas/presence rather than exact
    global counts, to stay independent of test execution order elsewhere.
    """

    def test_create_restocking_order_rejects_empty_selection(self, client):
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 10000, "item_skus": []}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_rejects_negative_budget(self, client):
        response = client.post(
            "/api/restocking-orders",
            json={"budget": -50, "item_skus": [AFFORDABLE_SKU]}
        )
        assert response.status_code == 400

    def test_create_restocking_order_rejects_unaffordable_sku(self, client):
        """A SKU that isn't affordable at the given budget must be rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 100, "item_skus": [AFFORDABLE_SKU]}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_rejects_sku_with_no_inventory_match(self, client):
        """A SKU that's always excluded (no inventory record) is never orderable."""
        excluded_sku = next(iter(EXCLUDED_SKUS))
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 100000, "item_skus": [excluded_sku]}
        )
        assert response.status_code == 400

    def test_create_restocking_order_happy_path(self, client):
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 10000, "item_skus": [AFFORDABLE_SKU]}
        )
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["lead_time_days"] == 10
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == AFFORDABLE_SKU
        assert order["items"][0]["quantity"] == AFFORDABLE_QUANTITY
        assert order["total_value"] == AFFORDABLE_LINE_COST
        assert re.match(r"^ORD-\d{4}-\d{4}$", order["order_number"])

        order_date = datetime.fromisoformat(order["order_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        assert (expected_delivery - order_date).days == 10

    def test_create_restocking_order_appears_in_orders_endpoint(self, client):
        """The submitted order must show up through the existing orders endpoint
        (this is what the Orders tab's Submitted Orders section relies on)."""
        create_response = client.post(
            "/api/restocking-orders",
            json={"budget": 10000, "item_skus": [AFFORDABLE_SKU]}
        )
        assert create_response.status_code == 201
        created_order = create_response.json()

        orders_response = client.get("/api/orders?status=Submitted")
        assert orders_response.status_code == 200

        submitted_orders = orders_response.json()
        order_ids = {o["id"] for o in submitted_orders}
        assert created_order["id"] in order_ids

        matching = next(o for o in submitted_orders if o["id"] == created_order["id"])
        assert matching["lead_time_days"] == 10
        assert matching["status"] == "Submitted"

    def test_create_restocking_order_number_does_not_collide(self, client):
        """Placing two orders back-to-back must yield distinct order numbers."""
        first = client.post(
            "/api/restocking-orders",
            json={"budget": 10000, "item_skus": [AFFORDABLE_SKU]}
        ).json()
        second = client.post(
            "/api/restocking-orders",
            json={"budget": 10000, "item_skus": [AFFORDABLE_SKU]}
        ).json()

        assert first["id"] != second["id"]
        assert first["order_number"] != second["order_number"]
