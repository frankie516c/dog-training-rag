from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.chat_service import ChatService, ChatServiceUnavailable
from backend.app.config import Settings, get_settings
from backend.app.data_validation import DataPaths
from backend.app.domain import ChatErrorResponse, ChatRequest, ChatResponse
from backend.app.embeddings import BgeM3EmbeddingProvider
from backend.app.generation import OpenAICompatibleGenerationProvider
from backend.app.retrieval import EvidenceRetrieval

CHAT_NOT_READY_MESSAGE = "검증된 근거를 검색하는 기능을 준비 중입니다."


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


def create_app(
    settings: Settings | None = None,
    *,
    chat_service: ChatService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(title=resolved_settings.app_name, version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    resolved_chat_service = chat_service or _create_chat_service(resolved_settings)

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
    async def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
        if resolved_chat_service is None:
            return _chat_not_ready_response()
        try:
            return await resolved_chat_service.answer(request)
        except ChatServiceUnavailable:
            return _chat_not_ready_response()

    return application


def _create_chat_service(settings: Settings) -> ChatService | None:
    base_url = settings.generation_base_url
    model = settings.generation_model
    if not base_url or not base_url.strip() or not model or not model.strip():
        return None
    api_key = settings.generation_api_key
    try:
        generator = OpenAICompatibleGenerationProvider(
            base_url=base_url,
            model=model,
            api_key=api_key.get_secret_value() if api_key is not None else None,
        )
        retriever = EvidenceRetrieval(
            paths=DataPaths(),
            qdrant_path=settings.qdrant_path,
            collection_name=settings.qdrant_collection,
            embedder=BgeM3EmbeddingProvider(
                model_id=settings.embedding_model_id,
                device=settings.embedding_device,
            ),
        )
    except (OSError, RuntimeError, ValueError):
        return None
    return ChatService(retriever=retriever, generator=generator)


def _chat_not_ready_response() -> JSONResponse:
    error = ChatErrorResponse(
        code="chat_not_ready",
        message=CHAT_NOT_READY_MESSAGE,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=error.model_dump(mode="json"),
    )


app = create_app()
