"""
Knowledge Base API endpoints
Статьи и инструкции
"""

from typing import List, Dict
from fastapi import APIRouter, HTTPException
from app.services.kb_service import get_all_articles, get_article_by_id

router = APIRouter()

@router.get("/articles")
async def list_articles():
    """Get all articles summary."""
    articles = get_all_articles()
    return [{"id": a["id"], "title": a["title"], "category": a["category"]} for a in articles]

@router.get("/articles/{article_id}")
async def get_article(article_id: str):
    """Get full article content."""
    article = get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
