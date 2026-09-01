"""Analytics freshness endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.analytics_freshness import get_freshness
from .auth import get_current_user
from ..models import entities as ent

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/freshness")
def analytics_freshness(
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"freshness": get_freshness(db)}
