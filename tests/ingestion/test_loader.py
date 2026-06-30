# Loader pipeline regression tests (CLAUDE.md S2.1).
#
# Two kinds of cases are covered:
#   1. The real catalog.json - proves the full pipeline (repair -> sanitize ->
#      validate) produces the expected valid/quarantine counts end-to-end.
#   2. Synthetic malformed records - the real catalog has zero records that
#      actually fail schema validation (see Task 1's full-catalog parse
#      test), so quarantine behavior can only be proven with fixtures built
#      specifically to fail.

import json
from pathlib import Path

import pytest

from app.ingestion.loader import load_catalog_from_file, load_catalog_records
from app.models.entities import PriceState

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"


@pytest.fixture(scope="module")
def result():
    return load_catalog_from_file(CATALOG_PATH)


def test_every_real_record_is_accounted_for(result):
    raw_count = len(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))
    assert result.report.total_records == raw_count
    assert result.report.total_valid + result.report.total_quarantined == raw_count


def test_real_catalog_has_zero_quarantines(result):
    # Every anomaly in the real dataset was deliberately modeled as a valid
    # state in Task 1 (price_state, independent available/stock_qty, etc.),
    # not a validation failure - so nothing here should be quarantined.
    assert result.report.total_valid == 97
    assert result.report.total_quarantined == 0
    assert result.quarantined == ()


def test_missing_price_key_is_valid_not_quarantined(result):
    # Explicit divergence from "quarantine prod_noprice_001": CLAUDE.md S3.2
    # and the Task 1 models define a missing price key as PriceState.MISSING,
    # a valid, tracked state - not a schema failure. Quarantining it would
    # silently remove a real, sellable-once-priced product from the catalog
    # and would contradict test_missing_price_key_is_distinct_from_null in
    # tests/models/test_entities.py.
    entity = next(e for e in result.valid_records if e.id == "prod_noprice_001")
    assert entity.price is None
    assert entity.price_state is PriceState.MISSING
    assert result.report.price_state_counts[PriceState.MISSING.value] == 1


def test_price_coercion_count_matches_known_string_price_records(result):
    # prod_str_001 ("129.00") and prod_str_002 ("59.00") are the only two
    # records with a string-typed price in the real catalog (CLAUDE.md S7).
    assert result.report.price_coercions_executed == 2


def test_price_state_counts_match_known_anomalies(result):
    counts = result.report.price_state_counts
    assert counts[PriceState.NULL.value] == 3        # prod_null_001, gift_001, gift_002
    assert counts[PriceState.MISSING.value] == 1      # prod_noprice_001
    assert counts[PriceState.NON_POSITIVE.value] == 1  # prod_zero_001
    assert counts[PriceState.NORMAL.value] == 90


def test_injection_flagged_count_matches_known_anomalies(result):
    # Only prod_inject_001 (description) and prod_inject_002 (top_review)
    # contain injection signatures in the real catalog.
    assert result.report.injection_flagged_count == 2


def test_flagged_records_have_redacted_text(result):
    inject_1 = next(e for e in result.valid_records if e.id == "prod_inject_001")
    inject_2 = next(e for e in result.valid_records if e.id == "prod_inject_002")
    assert "SYSTEM:" not in inject_1.description
    assert "Assistant:" not in inject_2.top_review
    assert "</review>" not in inject_2.top_review


def test_mojibake_is_repaired_through_the_full_pipeline(result):
    fr_sibling = next(e for e in result.valid_records if e.id == "prod_000_fr")
    assert "Ã" not in fr_sibling.description  # no leftover corruption artifacts


def test_html_is_stripped_through_the_full_pipeline(result):
    html_record = next(e for e in result.valid_records if e.id == "prod_html_001")
    assert "<p>" not in html_record.description
    assert "<b>" not in html_record.description


def test_trailing_whitespace_is_stripped_through_the_full_pipeline(result):
    dupe_c = next(e for e in result.valid_records if e.id == "prod_dupe_c")
    assert dupe_c.name == "Classic White Tee"


# --- Synthetic malformed records: prove the quarantine path actually fires ---

UNKNOWN_TYPE_RECORD = {
    "id": "bad_unknown_type",
    "type": "subscription",
    "name": "Mystery Plan",
    "market_id": "us",
    "language": "en",
    "description": "Not a real catalog type.",
}

MISSING_REQUIRED_FIELD_RECORD = {
    # no "id" at all
    "type": "page",
    "name": "Orphan Page",
    "market_id": "us",
    "language": "en",
    "description": "Missing its id field entirely.",
}

UNPARSEABLE_PRICE_RECORD = {
    "id": "bad_unparseable_price",
    "type": "product",
    "product_group_id": "bad_unparseable_price",
    "market_id": "us",
    "language": "en",
    "name": "Broken Price Product",
    "category": "apparel",
    "price": "contact us for pricing",
    "currency": "USD",
    "description": "Price cannot be parsed as a number.",
    "tags": ["apparel"],
    "stock_qty": 1,
    "available": True,
    "rating": 4.0,
    "review_count": 1,
}

VALID_MINIMAL_PAGE_RECORD = {
    "id": "good_minimal_page",
    "type": "page",
    "name": "Good Page",
    "market_id": "us",
    "language": "en",
    "description": "A perfectly valid record.",
}

SYNTHETIC_RECORDS = [
    UNKNOWN_TYPE_RECORD,
    MISSING_REQUIRED_FIELD_RECORD,
    UNPARSEABLE_PRICE_RECORD,
    "not-a-record-at-all",
    VALID_MINIMAL_PAGE_RECORD,
]


def test_quarantine_path_never_raises_and_isolates_bad_records():
    synthetic_result = load_catalog_records(SYNTHETIC_RECORDS)
    assert synthetic_result.report.total_records == 5
    assert synthetic_result.report.total_valid == 1
    assert synthetic_result.report.total_quarantined == 4
    assert synthetic_result.valid_records[0].id == "good_minimal_page"


def test_quarantined_records_carry_id_and_error_when_available():
    synthetic_result = load_catalog_records(SYNTHETIC_RECORDS)
    quarantined_by_id = {q.record_id: q for q in synthetic_result.quarantined}
    assert "bad_unknown_type" in quarantined_by_id
    assert "bad_unparseable_price" in quarantined_by_id
    assert quarantined_by_id["bad_unknown_type"].error  # non-empty validation error text
    # The non-dict entry and the missing-id record both surface with record_id=None.
    none_id_quarantines = [q for q in synthetic_result.quarantined if q.record_id is None]
    assert len(none_id_quarantines) == 2
