from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class Lead:
    source: str
    source_id: str
    title: str
    url: str
    description: str = ""
    budget: str = ""
    category: str = ""
    published_at: Optional[str] = None
    raw_published: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    score: int = 0

