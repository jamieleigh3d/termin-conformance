"""Conformance — v0.8 auto-CRUD list-endpoint query params.

Every conforming runtime must implement the following query parameter
contract on auto-generated list endpoints (`GET /api/v1/<content>`):

  ?limit=N         bound the response to at most N records
  ?offset=N        skip the first N records
  ?sort=field      sort ascending by a schema field
  ?sort=field:asc  explicit ascending
  ?sort=field:desc descending
  ?<field>=<value> equality filter on a schema field

Validation:
  - limit must be a non-negative integer <= a sane cap (1000).
  - offset must be a non-negative integer.
  - sort field must exist on the schema.
  - sort direction must be 'asc' or 'desc'.
  - filter field must exist on the schema.
  - values are always parameterized — SQL-injection-shaped values are
    harmless (they match no record).

Conforming runtimes that violate any of these requirements fail this
suite.
"""

import pytest


@pytest.fixture(autouse=True)
def _authenticated(warehouse):
    warehouse.set_role("warehouse manager")
    yield


class TestListEndpointPagination:
    def test_list_without_params_returns_all(self, warehouse):
        r = warehouse.get("/api/v1/products")
        assert r.status_code == 200
        # warehouse seed has exactly 6 products
        assert len(r.json()) >= 6

    def test_limit_bounds_response(self, warehouse):
        r = warehouse.get("/api/v1/products?limit=3")
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_offset_skips_records(self, warehouse):
        r_all = warehouse.get("/api/v1/products").json()
        r = warehouse.get("/api/v1/products?offset=3").json()
        assert len(r) == max(0, len(r_all) - 3)

    def test_limit_zero_returns_empty(self, warehouse):
        r = warehouse.get("/api/v1/products?limit=0")
        assert r.status_code == 200
        assert r.json() == []

    def test_limit_exceeds_total_returns_all(self, warehouse):
        # 500 is well below the 1000 cap and above any reasonable seed count.
        r = warehouse.get("/api/v1/products?limit=500")
        assert r.status_code == 200
        assert len(r.json()) >= 6

    def test_negative_limit_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?limit=-1")
        assert r.status_code == 400

    def test_negative_offset_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?offset=-1")
        assert r.status_code == 400

    def test_non_integer_limit_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?limit=abc")
        assert r.status_code == 400

    def test_limit_above_cap_rejected(self, warehouse):
        # The spec requires runtimes to enforce a cap. Any value > 1000
        # must be rejected.
        r = warehouse.get("/api/v1/products?limit=100000")
        assert r.status_code == 400


class TestListEndpointFiltering:
    def test_filter_by_category_returns_matching_only(self, warehouse):
        r = warehouse.get("/api/v1/products?category=raw material")
        assert r.status_code == 200
        body = r.json()
        assert len(body) >= 1
        assert all(row["category"] == "raw material" for row in body)

    def test_filter_unknown_field_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?zzz_nonexistent=foo")
        assert r.status_code == 400

    def test_filter_no_match_returns_empty(self, warehouse):
        r = warehouse.get("/api/v1/products?category=not-a-real-category-xyz")
        assert r.status_code == 200
        assert r.json() == []

    def test_filter_combined_with_pagination(self, warehouse):
        r = warehouse.get("/api/v1/products?category=raw material&limit=1")
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestListEndpointSorting:
    def test_sort_by_known_field_ascending_default(self, warehouse):
        r = warehouse.get("/api/v1/products?sort=sku")
        assert r.status_code == 200
        skus = [row["sku"] for row in r.json()]
        assert skus == sorted(skus)

    def test_sort_explicit_desc(self, warehouse):
        r = warehouse.get("/api/v1/products?sort=sku:desc")
        assert r.status_code == 200
        skus = [row["sku"] for row in r.json()]
        assert skus == sorted(skus, reverse=True)

    def test_sort_unknown_field_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?sort=not_a_real_column")
        assert r.status_code == 400

    def test_sort_invalid_direction_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?sort=sku:sideways")
        assert r.status_code == 400


class TestListEndpointSecurityInvariants:
    """Defense in depth — identifier-shaped query params that look like
    SQL injection must be rejected at the schema-lookup gate before
    reaching the storage layer. Filter VALUES are parameterized and
    harmless."""

    def test_sql_injection_in_sort_field_rejected(self, warehouse):
        r = warehouse.get("/api/v1/products?sort=sku;DROP TABLE products")
        assert r.status_code == 400
        # Sanity: products still listable.
        r2 = warehouse.get("/api/v1/products")
        assert r2.status_code == 200
        assert len(r2.json()) >= 6

    def test_sql_injection_in_filter_value_safely_parameterized(self, warehouse):
        r = warehouse.get("/api/v1/products?category='; DROP TABLE products; --")
        assert r.status_code == 200
        assert r.json() == []
        # Sanity.
        r2 = warehouse.get("/api/v1/products")
        assert len(r2.json()) >= 6
