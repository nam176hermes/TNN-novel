from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.mobile_api.schemas import (
    StyleProfileDefaultResponse,
    StyleProfileDefaultUpdate,
    StyleProfileListResponse,
)
from app.mobile_api.services.style_profile_service import StyleProfileService

router = APIRouter(prefix="/api/style-profiles", tags=["style-profiles"])


def get_style_profile_service():
    return StyleProfileService()


@router.get("", response_model=StyleProfileListResponse)
async def list_profiles(
    svc: StyleProfileService = Depends(get_style_profile_service),
):
    return {"profiles": svc.list_profiles()}


@router.get("/default", response_model=StyleProfileDefaultResponse)
async def get_default_profile(
    svc: StyleProfileService = Depends(get_style_profile_service),
):
    profile = svc.get_default()
    if profile is None:
        raise HTTPException(status_code=404, detail="Default style profile not found")
    return {"profile": profile}


@router.patch("/default", response_model=dict)
async def set_default_profile(
    update: StyleProfileDefaultUpdate,
    svc: StyleProfileService = Depends(get_style_profile_service),
):
    profile = svc.set_default(update.style_profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Style profile not found")
    return {"message": "Default style profile updated", "default": profile}
