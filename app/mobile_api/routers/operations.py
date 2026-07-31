from __future__ import annotations

from fastapi import APIRouter

from app.mobile_api.dependencies import get_data_dir, get_db_path
from app.mobile_api.services.operational_metrics_service import OperationalMetricsService


router = APIRouter(prefix="/api/ops", tags=["operations"])
_services: dict[tuple[str, str], OperationalMetricsService] = {}


def get_operational_metrics_service() -> OperationalMetricsService:
    db_path = get_db_path()
    data_dir = get_data_dir()
    key = (str(db_path), str(data_dir))
    service = _services.get(key)
    if service is None:
        service = OperationalMetricsService(db_path=db_path, data_dir=data_dir)
        _services.clear()
        _services[key] = service
    return service


@router.get("/metrics")
async def operational_metrics() -> dict:
    return get_operational_metrics_service().snapshot()
