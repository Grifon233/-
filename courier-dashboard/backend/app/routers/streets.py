"""GET /streets — активные отметки для карты."""
from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas import Street
from app.services.sightings import store

router = APIRouter()


@router.get("/streets", response_model=list[Street])
def list_streets(response: Response, city: str | None = Query(default=None, max_length=100)) -> list[Street]:
    """Без города возвращает все улицы, с городом — только его отметки."""
    response.headers["Cache-Control"] = "no-store"
    return store.list_streets(city=city)


@router.get("/streets/{street_id:path}", response_model=Street)
def get_street(street_id: str, response: Response) -> Street:
    """Цитаты по конкретной улице (для попапа по тапу)."""
    item = store.get_street(street_id)
    if item is None:
        raise HTTPException(status_code=404, detail="street_not_active", headers={"Cache-Control": "no-store"})
    response.headers["Cache-Control"] = "no-store"
    return item
