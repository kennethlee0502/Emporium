# Mojibake repair and whitespace normalization (CLAUDE.md S2.1, S1.5).
#
# Runs once per field at load-time, never on the request path. Repairs
# UTF-8-decoded-as-Latin-1 corruption (e.g. "PiÃ¨ce" -> "pièce") and
# strips stray leading/trailing whitespace (e.g. prod_dupe_c's trailing
# space) so downstream search/matching/dedup work against normalized text.

import ftfy


def repair_text(text: str) -> str:
    """Fix mojibake encoding artifacts and trim surrounding whitespace."""
    return ftfy.fix_text(text).strip()
