# Text-repair regression tests (CLAUDE.md S2.1, S1.5).
#
# Note: the catalog.json now on disk already contains clean UTF-8 for its
# FR/DE fields ("pièce", "Kernstück") - the "PiÃ¨ce"-style corruption was an
# artifact of how the document was pasted into chat earlier, not the real
# file content. To still prove the repair logic against the exact
# corruption mechanism (UTF-8 bytes misdecoded as Latin-1), the mojibake
# fixtures below are constructed the same way the real corruption happens:
# clean_text.encode("utf-8").decode("latin-1"). The whitespace test, by
# contrast, anchors on a genuine on-disk anomaly: prod_dupe_c's trailing space.

import json
from pathlib import Path

import pytest

from app.ingestion.text_repair import repair_text

CATALOG_PATH = Path(__file__).resolve().parents[2] / "catalog.json"


def mojibake(clean_text: str) -> str:
    """Reproduce UTF-8-decoded-as-Latin-1 corruption, e.g. 'pièce' -> 'piÃ¨ce'."""
    return clean_text.encode("utf-8").decode("latin-1")


@pytest.fixture(scope="module")
def catalog_by_id():
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {record["id"]: record for record in raw}


@pytest.mark.parametrize(
    "clean_text",
    [
        "Un t-shirt en coton, pièce de base de la collection.",
        "Ein Baumwoll-T-Shirt, ein Kernstück der Kollektion.",
        "Carte Cadeau Numérique",
        "Café Noir Hoodie",
    ],
)
def test_mojibake_is_repaired(clean_text):
    corrupted = mojibake(clean_text)
    assert corrupted != clean_text  # sanity check the fixture actually corrupted something
    assert repair_text(corrupted) == clean_text


def test_trailing_whitespace_is_stripped_on_real_record(catalog_by_id):
    raw_name = catalog_by_id["prod_dupe_c"]["name"]
    assert raw_name.endswith(" ")  # confirm the on-disk anomaly is still present
    assert repair_text(raw_name) == "Classic White Tee"


def test_leading_and_trailing_whitespace_is_stripped():
    assert repair_text("  Heritage Denim Jacket  ") == "Heritage Denim Jacket"
    assert repair_text("\tWool Beanie\n") == "Wool Beanie"


def test_already_clean_text_is_untouched(catalog_by_id):
    clean_samples = [
        catalog_by_id["prod_001"]["name"],          # "Everyday Crew Tee - White"
        catalog_by_id["prod_000_fr"]["description"],  # already-correct accented French
        catalog_by_id["prod_uni_001"]["name"],        # already-correct "Café Noir Hoodie"
    ]
    for text in clean_samples:
        assert repair_text(text) == text


def test_repair_is_idempotent(catalog_by_id):
    candidates = [
        mojibake("Ein Baumwoll-T-Shirt, ein Kernstück der Kollektion."),
        catalog_by_id["prod_dupe_c"]["name"],
        "  already padded  ",
        catalog_by_id["prod_001"]["name"],
    ]
    for text in candidates:
        once = repair_text(text)
        twice = repair_text(once)
        assert once == twice
