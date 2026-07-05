"""GET /streets — занятые улицы для карты (см. docs/02 и docs/03)."""
from fastapi import APIRouter, HTTPException

from app.schemas import Street
from app.services.sightings import store

router = APIRouter()


@router.get("/streets", response_model=list[Street])
async def list_streets(city: str | None = None) -> list[Street]:
    """Список занятых (красных) улиц. Фильтр по городу: ?city=Москва"""
    return store.list_streets(city=city)


@router.get("/streets/{street_id:path}", response_model=Street)
async def get_street(street_id: str) -> Street:
    """Цитаты по конкретной улице (для попапа по тапу)."""
    s = store.get_street(street_id)
    if s is None:
        raise HTTPException(status_code=404, detail="street_not_active")
    return s
