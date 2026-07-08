"""Entry point for running the mobile API as a module: python -m app.mobile_api"""

from app.mobile_api.main import app

if __name__ == "__main__":
    import uvicorn
    from app.mobile_api.config import mobile_settings
    
    uvicorn.run(
        app,
        host=mobile_settings.host,
        port=mobile_settings.port,
        reload=False,
        log_level="info",
    )