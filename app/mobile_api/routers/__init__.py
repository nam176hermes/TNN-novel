from __future__ import annotations

from app.mobile_api.routers.auth import router as auth_router
from app.mobile_api.routers.health import router as health_router
from app.mobile_api.routers.books import router as books_router
from app.mobile_api.routers.import_routes import router as import_router
from app.mobile_api.routers.jobs import router as jobs_router
from app.mobile_api.routers.exports import router as exports_router
from app.mobile_api.routers.audio import router as audio_router
from app.mobile_api.routers.tts import router as tts_router
from app.mobile_api.routers.glossary import router as glossary_router
from app.mobile_api.routers.qa import router as qa_router
from app.mobile_api.routers.providers import router as providers_router
from app.mobile_api.routers.style_profiles import router as style_profiles_router
from app.mobile_api.routers.source_catalog import router as source_catalog_router
from app.mobile_api.routers.source_adapter_candidates import router as source_adapter_candidates_router

__all__ = [
    "auth_router",
    "health_router",
    "books_router",
    "import_router",
    "jobs_router",
    "exports_router",
    "audio_router",
    "tts_router",
    "glossary_router",
    "qa_router",
    "providers_router",
    "style_profiles_router",
    "source_catalog_router",
    "source_adapter_candidates_router",
]
