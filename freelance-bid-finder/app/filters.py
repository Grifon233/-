from __future__ import annotations

import re

from app.models import Lead
from app.utils import normalize_for_match


WORD_CHAR = r"0-9a-zа-яе"


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized = normalize_for_match(keyword)
    if not normalized:
        return False
    pattern = rf"(?<![{WORD_CHAR}]){re.escape(normalized)}(?![{WORD_CHAR}])"
    return re.search(pattern, text) is not None


def evaluate_lead(lead: Lead, config: dict) -> Lead:
    title = normalize_for_match(lead.title)
    description = normalize_for_match(lead.description)
    category = normalize_for_match(lead.category)
    full_text = f"{title} {description} {category}"
    weak_keywords = {
        normalize_for_match(keyword)
        for keyword in config.get("weak_keywords", [])
    }

    score = 0
    matched: list[str] = []

    for keyword in config["positive_keywords"]:
        is_weak = normalize_for_match(keyword) in weak_keywords
        if _contains_keyword(title, keyword):
            score += 2 if is_weak else 4
            matched.append(keyword)
        elif _contains_keyword(description, keyword):
            score += 1 if is_weak else 2
            matched.append(keyword)
        elif _contains_keyword(category, keyword) and not is_weak:
            score += 1
            matched.append(keyword)

    for keyword in config["negative_keywords"]:
        if _contains_keyword(full_text, keyword):
            score -= 4

    lead.matched_keywords = sorted(set(matched), key=lambda item: item.lower())
    lead.score = max(score, 0) if lead.matched_keywords else 0
    return lead


def is_relevant(lead: Lead, config: dict) -> bool:
    return evaluate_lead(lead, config).score >= int(config["min_score"])
