from fastapi import FastAPI

from app.api.routes import estimate, evaluators, experiments, folders, sessions

app = FastAPI(title="AutoResearch Platform", version="0.1.0")
app.include_router(experiments.router)
app.include_router(folders.router)
app.include_router(evaluators.router)
app.include_router(sessions.router)
app.include_router(estimate.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
