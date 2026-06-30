# catalog.json ingestion pipeline (CLAUDE.md S2.1).
#
# Per record: repair_text (Task 2) -> sanitize_text (Task 3) -> entity
# validation via the discriminated-union TypeAdapter (Task 1). A record that
# fails schema validation is quarantined (logged, excluded from the valid
# list) - it never raises out of load_catalog_records() and never takes
# down the rest of the catalog. Everything here runs once, at load-time;
# nothing in this module belongs on the request path.
#
# Note on scope: a record with a *missing* price key (e.g. prod_noprice_001)
# is NOT quarantined. CLAUDE.md S3.2 and the Task 1 models define "missing
# price" as one of four explicit, valid PriceState outcomes (NORMAL / NULL /
# MISSING / NON_POSITIVE) precisely so it does not need to be treated as a
# validation failure. Quarantine is reserved for records that genuinely fail
# the schema - unknown `type`, missing required identity/structural fields,
# or a price string that cannot be parsed as a number at all.

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import ValidationError

from app.ingestion.sanitizer import sanitize_text
from app.ingestion.text_repair import repair_text
from app.models.entities import PriceState, catalog_entity_adapter

logger = logging.getLogger(__name__)

_TEXT_FIELDS = ("name", "description", "top_review")


@dataclass(frozen=True)
class QuarantinedRecord:
    record_id: Optional[str]
    raw: Dict[str, Any]
    error: str


@dataclass(frozen=True)
class AnomalyReport:
    total_records: int
    total_valid: int
    total_quarantined: int
    price_coercions_executed: int
    price_state_counts: Dict[str, int]
    injection_flagged_count: int
    quarantined_ids: Tuple[Optional[str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoadResult:
    valid_records: Tuple[Any, ...]
    quarantined: Tuple[QuarantinedRecord, ...]
    report: AnomalyReport


def _clean_record_text(record: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Run repair_text + sanitize_text over every free-text field in a raw record."""
    cleaned = dict(record)
    flagged = False

    for fname in _TEXT_FIELDS:
        value = cleaned.get(fname)
        if isinstance(value, str):
            result = sanitize_text(repair_text(value))
            cleaned[fname] = result.clean_text
            flagged = flagged or result.is_flagged

    tags = cleaned.get("tags")
    if isinstance(tags, list):
        cleaned_tags = []
        for tag in tags:
            if isinstance(tag, str):
                result = sanitize_text(repair_text(tag))
                cleaned_tags.append(result.clean_text)
                flagged = flagged or result.is_flagged
            else:
                cleaned_tags.append(tag)
        cleaned["tags"] = cleaned_tags

    return cleaned, flagged


def load_catalog_records(raw_records: List[Any]) -> LoadResult:
    """Run the full ingestion pipeline over already-parsed JSON records."""
    valid: List[Any] = []
    quarantined: List[QuarantinedRecord] = []
    price_coercions_executed = 0
    price_state_counts: Dict[str, int] = {state.value: 0 for state in PriceState}
    injection_flagged_count = 0

    for record in raw_records:
        if not isinstance(record, dict):
            quarantined.append(
                QuarantinedRecord(record_id=None, raw=record, error="record is not a JSON object")
            )
            logger.warning("Quarantined non-object catalog record: %r", record)
            continue

        cleaned, flagged = _clean_record_text(record)
        if flagged:
            injection_flagged_count += 1
            logger.warning(
                "Sanitizer flagged suspected prompt-injection content in record id=%s",
                record.get("id"),
            )

        raw_price_was_string = isinstance(cleaned.get("price"), str)

        try:
            entity = catalog_entity_adapter.validate_python(cleaned)
        except ValidationError as exc:
            quarantined.append(
                QuarantinedRecord(record_id=record.get("id"), raw=record, error=str(exc))
            )
            logger.warning("Quarantined record id=%s: %s", record.get("id"), exc)
            continue

        valid.append(entity)

        price_state = getattr(entity, "price_state", None)
        if price_state is not None:
            price_state_counts[price_state.value] += 1
            if raw_price_was_string:
                price_coercions_executed += 1

    report = AnomalyReport(
        total_records=len(raw_records),
        total_valid=len(valid),
        total_quarantined=len(quarantined),
        price_coercions_executed=price_coercions_executed,
        price_state_counts=price_state_counts,
        injection_flagged_count=injection_flagged_count,
        quarantined_ids=tuple(q.record_id for q in quarantined),
    )

    logger.info(
        "Catalog ingestion complete: %d valid, %d quarantined, %d flagged for injection, "
        "%d price coercions",
        report.total_valid,
        report.total_quarantined,
        report.injection_flagged_count,
        report.price_coercions_executed,
    )

    return LoadResult(valid_records=tuple(valid), quarantined=tuple(quarantined), report=report)


def load_catalog_from_file(path: Union[str, Path]) -> LoadResult:
    """Read catalog.json from disk and run it through load_catalog_records()."""
    raw_records = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_catalog_records(raw_records)
