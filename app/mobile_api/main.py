from pathlib import Path
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT
from app.database.db import init_db
from app.mobile_api.auth import get_auth_bypass_user
from app.mobile_api.config import assert_public_deploy_safe, auth_bypass_enabled, mobile_settings
from app.mobile_api.dependencies import get_db_path, get_data_dir
from app.mobile_api.private_cache import apply_private_no_store_headers
from app.mobile_api.private_assets import (
    asset_request_has_traversal,
    asset_token_from_request,
    authenticate_asset_request,
    resolve_private_asset,
    set_asset_access_cookie,
)
from app.mobile_api.public_mode import is_public_request
from app.mobile_api.session_auth import AccessTokenError, validate_access_token
from app.mobile_api.routers import (
    auth_router,
    health_router,
    books_router,
    import_router,
    jobs_router,
    exports_router,
    audio_router,
    tts_router,
    glossary_router,
    qa_router,
    providers_router,
    style_profiles_router,
    source_catalog_router,
    source_adapter_candidates_router,
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/ready",
    "/api/version",
    "/api/auth/login",
    "/api/auth/refresh",
}
logger = logging.getLogger(__name__)
PUBLIC_DOC_PATHS = {"/docs", "/openapi.json", "/redoc"}
SENSITIVE_PUBLIC_PATH_PREFIXES = (
    "/.env",
    "/data/",
    "/backups/",
    "/inbox/",
    "/output/",
)
SENSITIVE_PUBLIC_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".pem", ".key")


def _is_private_audio_api_path(path: str) -> bool:
    parts = path.strip("/").split("/")
    return (
        len(parts) in {6, 7}
        and parts[0] == "api"
        and parts[1] == "books"
        and parts[3] == "chapters"
        and parts[5] == "audio"
        and (len(parts) == 6 or parts[6] == "download")
    )


def _resolved_web_dist_dir() -> Path:
    web_dist_dir = Path(mobile_settings.web_dist_dir)
    if web_dist_dir.is_absolute():
        return web_dist_dir
    return PROJECT_ROOT / web_dist_dir


def _is_sensitive_public_path(path: str) -> bool:
    lowered = path.lower()
    if any(lowered == prefix.rstrip("/") or lowered.startswith(prefix) for prefix in SENSITIVE_PUBLIC_PATH_PREFIXES):
        return True
    return lowered.endswith(SENSITIVE_PUBLIC_SUFFIXES)


def _prepare_runtime() -> None:
    get_data_dir()
    init_db(get_db_path())

    # Initialize captcha solver if API key is configured
    captcha_key = os.getenv("CAPTCHA_API_KEY")
    if captcha_key:
        from app.utils.captcha_solver import init_captcha_solver
        init_captcha_solver(captcha_key, os.getenv("CAPTCHA_PROVIDER", "2captcha"))


def _mount_web_app(app: FastAPI) -> None:
    if not mobile_settings.serve_web:
        return

    dist_dir = _resolved_web_dist_dir()
    index_path = dist_dir / "index.html"
    if not index_path.exists():
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/", include_in_schema=False)
    async def web_index():
        return FileResponse(index_path)

    @app.get("/{path:path}", include_in_schema=False)
    async def web_spa_fallback(path: str):
        if path.startswith("api/") or path in {"docs", "openapi.json", "redoc"}:
            raise HTTPException(status_code=404)
        dist_root = dist_dir.resolve()
        candidate = (dist_root / path).resolve()
        if candidate.is_file() and (candidate.parent == dist_root or dist_root in candidate.parents):
            return FileResponse(candidate)
        return FileResponse(index_path)


def _mount_private_asset_routes(app: FastAPI) -> None:
    @app.get("/covers/{asset_path:path}", include_in_schema=False)
    async def private_cover(asset_path: str, request: Request):
        authenticate_asset_request(request)
        path = resolve_private_asset(get_data_dir() / "covers", asset_path)
        response = FileResponse(path)
        apply_private_no_store_headers(response.headers)
        return response

    @app.get("/book-assets/{asset_path:path}", include_in_schema=False)
    async def private_book_asset(asset_path: str, request: Request):
        authenticate_asset_request(request)
        path = resolve_private_asset(get_data_dir() / "book_assets", asset_path)
        response = FileResponse(path)
        apply_private_no_store_headers(response.headers)
        return response


def create_app() -> FastAPI:
    try:
        assert_public_deploy_safe(mobile_settings)
    except RuntimeError:
        logger.exception("Startup safety gate failed")
        raise
    _prepare_runtime()
    app = FastAPI(
        title="Novel Pipeline Mobile API",
        version=mobile_settings.version,
        docs_url=None if mobile_settings.public_deploy else "/docs",
        openapi_url=None if mobile_settings.public_deploy else "/openapi.json",
        redoc_url=None if mobile_settings.public_deploy else "/redoc",
    )

    # CORS for Flutter
    app.add_middleware(
        CORSMiddleware,
        allow_origins=mobile_settings.cors_origins,
        allow_origin_regex=None
        if mobile_settings.public_deploy
        else r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Protected API guard. Health/login/refresh stay public; all other /api routes
    # require a valid bearer token. A browser dashboard cannot safely carry a
    # shared REMOTE_API_KEY secret, so bearer auth is the enforced boundary.

    @app.middleware("http")
    async def protected_api_guard(request: Request, call_next):
        path = request.url.path
        public_request = is_public_request(request)
        auth_disabled = auth_bypass_enabled()
        if public_request and path in PUBLIC_DOC_PATHS:
            response = JSONResponse(status_code=404, content={"detail": "Not found"})
            apply_private_no_store_headers(response.headers)
            return response
        if public_request and _is_sensitive_public_path(path):
            response = JSONResponse(status_code=404, content={"detail": "Not found"})
            apply_private_no_store_headers(response.headers)
            return response
        if path.startswith(("/covers/", "/book-assets/")) and asset_request_has_traversal(path):
            response = JSONResponse(status_code=403, content={"detail": "Invalid asset path"})
            apply_private_no_store_headers(response.headers)
            return response
        if request.method == "OPTIONS":
            return await call_next(request)
        if path.startswith(("/covers/", "/book-assets/")):
            response = await call_next(request)
            apply_private_no_store_headers(response.headers)
            return response
        if _is_private_audio_api_path(path):
            if not auth_disabled:
                try:
                    authenticate_asset_request(request)
                except HTTPException as exc:
                    response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                    apply_private_no_store_headers(response.headers)
                    return response
            response = await call_next(request)
            token = asset_token_from_request(request)
            if token:
                set_asset_access_cookie(response, token, secure=public_request)
            apply_private_no_store_headers(response.headers)
            return response
        if path in {"/api/auth/login", "/api/auth/refresh"}:
            response = await call_next(request)
            apply_private_no_store_headers(response.headers)
            return response
        if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
            return await call_next(request)
        if auth_disabled:
            request.state.user = get_auth_bypass_user()
            response = await call_next(request)
            apply_private_no_store_headers(response.headers)
            return response

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            response = JSONResponse(status_code=401, content={"detail": "Missing bearer token"})
            apply_private_no_store_headers(response.headers)
            return response

        try:
            request.state.user = validate_access_token(token)
        except AccessTokenError as exc:
            response = JSONResponse(status_code=401, content={"detail": str(exc)})
            apply_private_no_store_headers(response.headers)
            return response

        response = await call_next(request)
        set_asset_access_cookie(response, token, secure=public_request)
        apply_private_no_store_headers(response.headers)
        return response

    # Mount all routers
    app.include_router(auth_router)
    app.include_router(health_router)
    # Books router owns book, chapter, reader-state, reader-search, reader-AI, and X-Ray endpoints.
    app.include_router(books_router)
    app.include_router(import_router)
    app.include_router(jobs_router)
    app.include_router(exports_router)
    app.include_router(audio_router)
    app.include_router(tts_router)
    app.include_router(glossary_router)
    app.include_router(qa_router)
    app.include_router(providers_router)
    app.include_router(style_profiles_router)
    app.include_router(source_catalog_router)
    app.include_router(source_adapter_candidates_router)
    _mount_private_asset_routes(app)
    _mount_web_app(app)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.mobile_api.main:app",
        host=mobile_settings.host,
        port=mobile_settings.port,
        reload=False,
        log_level="info",
    )
