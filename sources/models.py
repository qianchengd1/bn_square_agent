from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialArticle:
    title: str | None
    content: str
    author: str | None = None
    url: str | None = None
    external_id: str | None = None
    source_created_at: str | None = None
