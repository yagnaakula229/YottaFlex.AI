import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
def ready(
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning(
            "Database readiness check failed",
            extra={"event": "database_readiness_failed"},
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Database is not ready") from exc

    return {"status": "ready"}