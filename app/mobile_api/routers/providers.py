from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.mobile_api.schemas import (
    CostEstimateRequest,
    CostEstimateResponse,
    ProviderTestRequest,
)
from app.mobile_api.audit import record_audit_event
from app.mobile_api.services.provider_service import ProviderService
from app.mobile_api.services.provider_secret_store import ProviderSecretStoreError

router = APIRouter(prefix="/api/providers", tags=["providers"])
logger = logging.getLogger(__name__)
PROVIDER_TEST_FAILURE_DETAIL = "Provider test failed. Check provider settings and server logs."
PROVIDER_TEST_TIMEOUT_DETAIL = (
    "Provider test timed out. Check provider timeout settings and server logs."
)


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
    http_request: Request,
    svc: ProviderService = Depends(get_provider_service),
):
    try:
        payload = await http_request.json()
    except (ValueError, UnicodeError):
        payload = None
    api_key = payload.get("api_key") if isinstance(payload, dict) else None
    if not isinstance(api_key, str):
        record_audit_event(
            event_type="provider_key_update",
            severity="warning",
            source="providers",
            message="Provider key update failed",
            request=http_request,
            details={"provider_id": provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=422, detail="Provider key request is invalid")
    try:
        provider = svc.update_provider_key(provider_id, api_key)
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
    except ProviderSecretStoreError as exc:
        logger.warning("Provider key storage operation failed for %s", provider_id)
        record_audit_event(
            event_type="provider_key_update",
            severity="error",
            source="providers",
            message="Provider key update failed",
            request=http_request,
            details={"provider_id": provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=503, detail="Provider key storage unavailable") from exc


@router.delete("/{provider_id}/key")
async def delete_provider_key(
    provider_id: str,
    http_request: Request,
    svc: ProviderService = Depends(get_provider_service),
):
    try:
        provider = svc.delete_provider_key(provider_id)
        record_audit_event(
            event_type="provider_key_delete",
            severity="info",
            source="providers",
            message="Provider key deleted",
            request=http_request,
            details={"provider_id": provider_id, "result": "success"},
        )
        return {"provider": provider}
    except ValueError as exc:
        message = str(exc)
        record_audit_event(
            event_type="provider_key_delete",
            severity="warning",
            source="providers",
            message="Provider key deletion failed",
            request=http_request,
            details={"provider_id": provider_id, "result": "failure"},
        )
        if message == f"Provider {provider_id} not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except ProviderSecretStoreError as exc:
        logger.warning("Provider key storage deletion failed for %s", provider_id)
        record_audit_event(
            event_type="provider_key_delete",
            severity="error",
            source="providers",
            message="Provider key deletion failed",
            request=http_request,
            details={"provider_id": provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=503, detail="Provider key storage unavailable") from exc


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
        return await svc.test_provider_async(request.provider_id, request.prompt)
    except (TimeoutError, httpx.TimeoutException) as exc:
        logger.warning("Provider test timed out for %s", request.provider_id)
        record_audit_event(
            event_type="provider_test_failure",
            severity="warning",
            source="providers",
            message="Provider test failed",
            request=http_request,
            details={"provider_id": request.provider_id, "result": "failure"},
        )
        raise HTTPException(status_code=504, detail=PROVIDER_TEST_TIMEOUT_DETAIL) from exc
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
        logger.warning("Provider test failed for %s", request.provider_id)
        raise HTTPException(status_code=502, detail=PROVIDER_TEST_FAILURE_DETAIL) from exc
    except httpx.HTTPError as exc:
        logger.warning("Provider test failed for %s", request.provider_id)
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
        logger.warning("Provider test failed for %s", request.provider_id)
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
