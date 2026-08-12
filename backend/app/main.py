from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.config import Settings, get_settings
from backend.app.domain import ChatErrorResponse, ChatRequest, ChatResponse

CHAT_NOT_READY_MESSAGE = "검증된 근거를 검색하는 기능을 준비 중입니다."


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

    @application.post(
        "/chat",
        response_model=ChatResponse,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ChatErrorResponse,
                "description": "The evidence-backed chat pipeline is not ready.",
            }
        },
        tags=["chat"],
    )
    async def chat(_request: ChatRequest) -> JSONResponse:
        error = ChatErrorResponse(
            code="chat_not_ready",
            message=CHAT_NOT_READY_MESSAGE,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error.model_dump(mode="json"),
        )

    return application


app = create_app()
