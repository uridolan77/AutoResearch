from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import estimate, evaluators, experiments, folders, sessions

app = FastAPI(title="AutoResearch Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(experiments.router)
app.include_router(folders.router)
app.include_router(evaluators.router)
app.include_router(sessions.router)
app.include_router(estimate.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
