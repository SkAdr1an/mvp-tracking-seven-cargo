from fastapi import FastAPI

app = FastAPI(title="7Seven Cargo MVP Tracking", version="0.1.0")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
