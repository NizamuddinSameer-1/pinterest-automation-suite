"""
Keyword packs — one stored vocabulary per trend dossier, shared by pins + blog.

Deterministic builder (no LLM): packs derive from scanned related queries so
re-scans are reproducible. The content lane may *draft* richer packs later;
this module owns the schema both paths must satisfy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.pipeline.pinterest_seo import FRAMEWORKS

PACK_VERSION = 1


@dataclass
class KeywordPack:
    primary: str
    long_tails: list[str] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    board_angle: str = ""
    negative_terms: list[str] = field(default_factory=list)
    pack_version: int = PACK_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeywordPack":
        return cls(
            primary=str(data.get("primary", "")),
            long_tails=list(data.get("long_tails") or []),
            hooks=list(data.get("hooks") or []),
            board_angle=str(data.get("board_angle", "")),
            negative_terms=list(data.get("negative_terms") or []),
            pack_version=int(data.get("pack_version", PACK_VERSION)),
        )


def build_pack(
    primary: str,
    related_queries: list[str] | None = None,
    board_angle: str = "",
    variations_count: int = 4,
) -> KeywordPack:
    """
    Deterministically build a pack: first related query family becomes the
    primary, the rest become long-tails, hook frameworks rotate round-robin
    so no two variations share an angle.
    """
    queries = [q.strip() for q in (related_queries or []) if q and q.strip()]
    head = primary.strip() or (queries[0] if queries else "curated find")
    tails = [q for q in queries if q.lower() != head.lower()][:8]
    hooks = [
        {
            "variation_index": i + 1,
            "framework": FRAMEWORKS[i % len(FRAMEWORKS)]["name"],
        }
        for i in range(max(1, variations_count))
    ]
    return KeywordPack(
        primary=head, long_tails=tails, hooks=hooks,
        board_angle=board_angle, pack_version=PACK_VERSION,
    )
