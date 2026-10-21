from fastapi import FastAPI

app = FastAPI(title="RevenueLens")


@app.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
