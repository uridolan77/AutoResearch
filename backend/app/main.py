from fastapi import FastAPI

from app.api.routes import experiments

app = FastAPI(title="AutoResearch Platform", version="0.1.0")
app.include_router(experiments.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
