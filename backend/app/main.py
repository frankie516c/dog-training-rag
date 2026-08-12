from fastapi import FastAPI
from pydantic import BaseModel

from backend.app.config import Settings, get_settings


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(title=resolved_settings.app_name, version="0.1.0")

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            app=resolved_settings.app_name,
            environment=resolved_settings.environment,
        )

    return application


app = create_app()
