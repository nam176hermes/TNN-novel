from __future__ import annotations

import logging

import requests
from fastapi import APIRouter, Depends, HTTPException, Request

from app.mobile_api.schemas import (
    CostEstimateRequest,
    CostEstimateResponse,
    ProviderKeyUpdateRequest,
    ProviderTestRequest,
)
from app.mobile_api.audit import record_audit_event
from app.mobile_api.services.provider_service import ProviderService

router = APIRouter(prefix="/api/providers", tags=["providers"])
logger = logging.getLogger(__name__)
PROVIDER_TEST_FAILURE_DETAIL = "Provider test failed. Check provider settings and server logs."


def get_provider_service() -> ProviderService:
    return ProviderService()


@router.get("")
async def list_providers(svc: ProviderService = Depends(get_provider_service)):
    return {"providers": svc.list_providers()}


@router.get("/defaults")
async def get_defaults(svc: ProviderService = Depends(get_provider_service)):
    return {"defaults": svc.get_defaults()}


@router.post("/{provider_id}/key")
async def update_provider_key(
    provider_id: str,
    request: ProviderKeyUpdateRequest,
    http_request: Request,
    svc: ProviderService = Depends(get_provider_service),
):
    try:
        provider = svc.update_provider_key(provider_id, request.api_key)
        record_audit_event(
            event_type="provider_key_update",
            severity="info",
            source="providers",
            message="Provider key updated",
            request=http_request,
            details={"provider_id": provider_id, "result": "success"},
        )
        return {"provider": provider}
    except ValueError as exc:
        message = str(exc)
        record_audit_event(
            event_type="provider_key_update",
            severity="warning",
            source="providers",
            message="Provider key update failed",
            request=http_request,
            details={"provider_id": provider_id, "result": "failure"},
        )
        if message == f"Provider {provider_id} not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_cost(
    request: CostEstimateRequest,
    svc: ProviderService = Depends(get_provider_service),
):
    try:
        return svc.estimate_cost(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/test")
async def test_provider(
    request: ProviderTestRequest,
    http_request: Request,
    svc: ProviderService = Depends(get_provider_service),
):
    try:
        return svc.test_provider(request.provider_id, request.prompt)
    except ValueError as exc:
        record_audit_event(
            event_type="provider_test_failure",
            severity="warning",
            source="providers",
            message="Provider test failed",
            request=http_request,
            details={"provider_id": request.provider_id, "result": "failure"},
        )
        if str(exc) == f"Provider {request.provider_id} not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(exc).startswith(f"Provider {request.provider_id} requires "):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.warning("Provider test failed for %s", request.provider_id, exc_info=True)
        raise HTTPException(status_code=502, detail=PROVIDER_TEST_FAILURE_DETAIL) from exc
    except requests.RequestException as exc:
        logger.warning("Provider test failed for %s", request.provider_id, exc_info=True)
        record_audit_event(
            event_type="provider_test_failure",
            severity="warning",
            source="providers",
            message="Provider test failed",
            request=http_request,
            details={"provider_id": request.provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=502, detail=PROVIDER_TEST_FAILURE_DETAIL) from exc
    except Exception as exc:
        logger.warning("Provider test failed for %s", request.provider_id, exc_info=True)
        record_audit_event(
            event_type="provider_test_failure",
            severity="warning",
            source="providers",
            message="Provider test failed",
            request=http_request,
            details={"provider_id": request.provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=502, detail=PROVIDER_TEST_FAILURE_DETAIL) from exc


@router.get("/usage")
async def usage_summary(svc: ProviderService = Depends(get_provider_service)):
    return {"usage": svc.usage_summary()}
