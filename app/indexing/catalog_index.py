# In-memory index builder + read-only accessors (CLAUDE.md S2.3, S3.3).
#
# Built once, from the loader's valid_records, at startup. Every accessor is
# an O(1) dict lookup - no parsing, no scanning, no sanitization on this path
# (that already happened in ingestion). Underlying mappings are wrapped in
# MappingProxyType so mutation from outside this module raises TypeError
# rather than silently corrupting shared state across requests/instances.

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app.models.entities import CatalogEntity

_EMPTY_MAPPING: Mapping[str, Any] = MappingProxyType({})
_EMPTY_IDS: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogIndex:
    by_id: Mapping[str, Any]
    by_group: Mapping[str, Mapping[str, Any]]
    by_market_category: Mapping[Tuple[str, Optional[str]], Tuple[str, ...]]
    by_tag: Mapping[str, Tuple[str, ...]]

    def get_by_id(self, entity_id: str) -> Optional[Any]:
        return self.by_id.get(entity_id)

    def get_group_siblings(self, product_group_id: str) -> Mapping[str, Any]:
        """market_id -> entity for every localized sibling of a product group."""
        return self.by_group.get(product_group_id, _EMPTY_MAPPING)

    def get_ids_by_market_category(self, market_id: str, category: Optional[str]) -> Tuple[str, ...]:
        return self.by_market_category.get((market_id, category), _EMPTY_IDS)

    def get_ids_by_tag(self, tag: str) -> Tuple[str, ...]:
        return self.by_tag.get(tag, _EMPTY_IDS)


def build_catalog_index(entities: Iterable[CatalogEntity]) -> CatalogIndex:
    """Build all read-only indices from a collection of validated entities."""
    by_id: Dict[str, Any] = {}
    by_group: Dict[str, Dict[str, Any]] = {}
    by_market_category: Dict[Tuple[str, Optional[str]], List[str]] = {}
    by_tag: Dict[str, List[str]] = {}

    for entity in entities:
        by_id[entity.id] = entity

        product_group_id = getattr(entity, "product_group_id", None)
        if product_group_id is not None:
            by_group.setdefault(product_group_id, {})[entity.market_id] = entity

        category_key = (entity.market_id, entity.category)
        by_market_category.setdefault(category_key, []).append(entity.id)

        tags = getattr(entity, "tags", None)
        if tags:
            for tag in tags:
                by_tag.setdefault(tag, []).append(entity.id)

    return CatalogIndex(
        by_id=MappingProxyType(dict(by_id)),
        by_group=MappingProxyType({k: MappingProxyType(dict(v)) for k, v in by_group.items()}),
        by_market_category=MappingProxyType({k: tuple(v) for k, v in by_market_category.items()}),
        by_tag=MappingProxyType({k: tuple(v) for k, v in by_tag.items()}),
    )
