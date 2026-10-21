from fastapi import FastAPI

from .auth import router as auth_router

app = FastAPI(title="RevenueLens")


@app.get("/health")
def health():
    try:
        from .config import get_settings

        settings = get_settings()
        return {"status": "ok", "company": settings.company_name}
    except RuntimeError:
        return {"status": "ok"}


app.include_router(auth_router)
