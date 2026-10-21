from fastapi import FastAPI

from .auth import router as auth_router
from .dashboard import router as dashboard_router
from .fixes_routes import router as fixes_router
from .reports_routes import router as reports_router

app = FastAPI(title="RevenueLens", docs_url="/api-docs", redoc_url=None)


@app.get("/health")
def health():
    try:
        from .config import get_settings

        settings = get_settings()
        return {"status": "ok", "company": settings.company_name}
    except RuntimeError:
        return {"status": "ok"}


app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(fixes_router)
app.include_router(reports_router)
