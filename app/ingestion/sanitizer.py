# HTML stripping + prompt-injection pattern flagging (CLAUDE.md S2.1, S1.8, S5.1).
#
# Runs once per field at load-time, never on the request path. Every free-text
# field originating from catalog.json (name, description, tags, top_review)
# must pass through sanitize_text() before reaching an index, a response
# model, or any log line another LLM might read.
#
# Two distinct jobs, kept in one pass (CLAUDE.md S5.1 - do not conflate them):
#   1. HTML/markup stripping (nh3, allow-list to nothing) - content hygiene.
#   2. Prompt-injection pattern detection - role markers ("system:",
#      "assistant:"), imperative jailbreak phrasing ("ignore previous
#      instructions"), and fabricated structural boundaries (a closing tag
#      like "</review>" with no real opening tag, used to make catalog text
#      masquerade as the end of a document section or a chat turn).
#
# Flagged matches are redacted from clean_text (so the literal payload never
# reaches the calling agent) AND surfaced via is_flagged/matched_patterns, so
# the event is never silently dropped with no trace.

import re
from dataclasses import dataclass
from typing import Dict, Pattern, Tuple

import nh3

REDACTION_PLACEHOLDER = "[flagged content removed]"

# Plain-text role-marker / imperative injection signatures. Checked against
# the raw text and redacted from clean_text when matched.
TEXT_INJECTION_PATTERNS: Dict[str, Pattern] = {
    "role_marker_system": re.compile(r"\bsystem\s*:", re.IGNORECASE),
    "role_marker_assistant": re.compile(r"\bassistant\s*:", re.IGNORECASE),
    "ignore_previous_instructions": re.compile(
        r"ignore\s+(?:all\s+|any\s+)?previous\s+instructions", re.IGNORECASE
    ),
}

# Closing tags that correspond to ordinary content markup are never flagged -
# real HTML like "<p>...</p>" is a content-hygiene concern, not an attack.
# Any other closing tag (e.g. "</review>", "</system>") is not real HTML at
# all; it is a fabricated structural boundary, which is what we flag. It
# needs no separate redaction: nh3.clean() below strips all tag syntax
# regardless of name, so a flagged tag is already gone from clean_text.
_ORDINARY_HTML_CLOSING_TAGS = frozenset(
    {
        "p", "b", "i", "strong", "em", "span", "div", "br", "ul", "ol", "li",
        "a", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "code", "pre",
    }
)
_CLOSING_TAG_PATTERN = re.compile(r"</\s*([a-zA-Z][\w-]*)\s*>")


def _has_fake_closing_tag(text: str) -> bool:
    return any(
        match.group(1).lower() not in _ORDINARY_HTML_CLOSING_TAGS
        for match in _CLOSING_TAG_PATTERN.finditer(text)
    )


@dataclass(frozen=True)
class SanitizationResult:
    clean_text: str
    is_flagged: bool
    matched_patterns: Tuple[str, ...]


def sanitize_text(text: str) -> SanitizationResult:
    """Strip HTML and flag/redact prompt-injection patterns in one pass."""
    matched = {name for name, pattern in TEXT_INJECTION_PATTERNS.items() if pattern.search(text)}
    if _has_fake_closing_tag(text):
        matched.add("fake_closing_tag")
    matched_patterns = tuple(sorted(matched))

    clean_text = nh3.clean(text, tags=set())
    for name, pattern in TEXT_INJECTION_PATTERNS.items():
        if name in matched:
            clean_text = pattern.sub(REDACTION_PLACEHOLDER, clean_text)

    return SanitizationResult(
        clean_text=clean_text,
        is_flagged=bool(matched_patterns),
        matched_patterns=matched_patterns,
    )
