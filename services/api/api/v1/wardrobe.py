import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.core.database import get_db
from services.api.core.models import WardrobeItem
from services.api.core.security import get_current_user_id

router = APIRouter()


class WardrobeItemCreate(BaseModel):
    name: str = Field(..., max_length=256)
    image_url: str | None = None
    category: str | None = None


@router.get("/")
async def list_wardrobe(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WardrobeItem)
        .where(WardrobeItem.user_id == user_id)
    )
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "image_url": i.image_url,
                "category": i.category,
                "metadata": i.metadata_json,
            }
            for i in items
        ]
    }


@router.post("/")
async def add_wardrobe_item(
    body: WardrobeItemCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    item = WardrobeItem(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=body.name,
        image_url=body.image_url,
        category=body.category,
    )
    db.add(item)
    await db.commit()
    return {"id": item.id, "name": item.name}
