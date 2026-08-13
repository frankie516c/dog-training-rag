from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

BGE_M3_MODEL_ID = "BAAI/bge-m3"
BGE_M3_DIMENSION = 1_024


class EmbeddingProvider(Protocol):
    """Dense embedding boundary used by retrieval and deterministic test fakes."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class BgeM3EmbeddingProvider:
    """Lazy, normalized dense embeddings from a Sentence Transformers model."""

    def __init__(self, model_id: str = BGE_M3_MODEL_ID, device: str | None = None) -> None:
        self._model_id = model_id
        self._device = device
        self._model: SentenceTransformer | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return BGE_M3_DIMENSION

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        if any(len(vector) != self.dimension for vector in vectors):
            raise ValueError(
                f"embedding model {self.model_id!r} must return {self.dimension} dimensions"
            )
        return vectors

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_id, device=self._device)
        return self._model
