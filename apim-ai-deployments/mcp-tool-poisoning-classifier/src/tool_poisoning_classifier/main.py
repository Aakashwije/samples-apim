# Copyright (c) 2026, WSO2 LLC. (https://www.wso2.com).
#
# WSO2 LLC. licenses this file to you under the Apache License,
# Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the
# License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP API for the MCP tool poisoning classifier.

Endpoints:
    POST /classify  score tool metadata
    GET  /healthz   liveness: the process is up
    GET  /readyz    readiness: the model is loaded and verified

This service is internal. It is reachable only from the gateway and exists to
keep model inference — and the half-gigabyte of weights it needs — out of the
gateway process.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .classifier import (
    Classifier,
    ModelContractError,
    TextTooLongError,
    ToolPoisoningClassifier,
)
from .config import Settings, load_settings
from .schemas import (
    ClassifyRequest,
    ClassifyResponse,
    ClassifyResult,
    HealthResponse,
    ReadyResponse,
)

LOGGER = logging.getLogger(__name__)

# Spelled numerically: Starlette renamed both constants (…_UNPROCESSABLE_ENTITY
# to …_UNPROCESSABLE_CONTENT, …_REQUEST_ENTITY_TOO_LARGE to …_CONTENT_TOO_LARGE)
# and the old names warn on new versions while the new ones are missing on the
# older versions this service still supports.
HTTP_CONTENT_TOO_LARGE = 413
HTTP_UNPROCESSABLE_CONTENT = 422


class CapacityExceeded(Exception):
    """Raised when the service is already serving its maximum request count."""


class ConcurrencyLimiter:
    """Bounds in-flight classification requests.

    Rejecting past the limit keeps queue depth — and therefore the latency the
    gateway sees — bounded. The counter needs no lock: it is only ever touched
    from the event loop thread, and never across an await.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @contextmanager
    def slot(self) -> Iterator[None]:
        if self._active >= self._limit:
            raise CapacityExceeded()
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1


def create_app(
    settings: Settings | None = None,
    classifier: Classifier | None = None,
) -> FastAPI:
    """Build the application.

    Passing a classifier skips loading the real model, which is what the tests
    and the health tooling use.
    """
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level)

    owns_lifecycle = classifier is None
    model: Classifier = classifier or ToolPoisoningClassifier(settings)
    limiter = ConcurrencyLimiter(settings.max_concurrent_requests)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if owns_lifecycle:
            # Loaded once, at startup: a per-request load would add seconds of
            # latency and multiply memory use.
            await anyio.to_thread.run_sync(model.load)  # type: ignore[attr-defined]
        yield

    app = FastAPI(
        title="MCP Tool Poisoning Classifier",
        description=(
            "Scores MCP tool metadata with the wso2/tool-poisoning-detection SetFit model."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.classifier = model
    app.state.limiter = limiter

    def require_auth(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        """Authenticate the caller with a bearer token.

        Anonymous access exists only when it was configured explicitly; the
        settings refuse to build without either a key or that opt-in.
        """
        if not settings.api_key:
            return

        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="a bearer token is required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Constant-time: a timing-distinguishable comparison leaks the key.
        if not hmac.compare_digest(token, settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        """Liveness. The process is running and serving.

        Deliberately independent of the model: a liveness probe that fails
        while the model loads would restart the pod forever.
        """
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadyResponse)
    async def readyz() -> JSONResponse:
        """Readiness. The model is loaded, verified, and able to score."""
        if not model.ready:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=ReadyResponse(
                    status="loading", detail="the model is not loaded yet"
                ).model_dump(),
            )
        identity = model.identity
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=ReadyResponse(
                status="ready", model=identity.model, revision=identity.revision
            ).model_dump(),
        )

    @app.post(
        "/classify",
        response_model=ClassifyResponse,
        dependencies=[Depends(require_auth)],
    )
    async def classify(request: ClassifyRequest) -> ClassifyResponse:
        _validate_limits(request, settings)

        if not model.ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="the model is not loaded yet",
            )

        texts = [item.text for item in request.items]
        started = time.monotonic()

        try:
            with limiter.slot():
                scores = await anyio.to_thread.run_sync(model.score, texts)
        except CapacityExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "the classifier is at its concurrency limit of "
                    f"{settings.max_concurrent_requests}"
                ),
                headers={"Retry-After": "1"},
            ) from exc
        except TextTooLongError as exc:
            # Refused rather than truncated: a truncated score would be
            # reported as a complete inspection of the whole text.
            raise HTTPException(
                status_code=HTTP_CONTENT_TOO_LARGE,
                detail=str(exc),
            ) from exc
        except ModelContractError as exc:
            LOGGER.exception("the model violated its documented contract")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"model error: {exc}",
            ) from exc

        identity = model.identity
        LOGGER.info(
            "classified items=%d latency_ms=%d model=%s revision=%s",
            len(texts),
            int((time.monotonic() - started) * 1000),
            identity.model,
            identity.revision,
        )

        return ClassifyResponse(
            model=identity.model,
            revision=identity.revision,
            results=[
                ClassifyResult(id=item.id, poisoningScore=score)
                for item, score in zip(request.items, scores, strict=True)
            ],
        )

    @app.exception_handler(CapacityExceeded)
    async def _capacity_handler(_: Request, __: CapacityExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "the classifier is at its concurrency limit"},
            headers={"Retry-After": "1"},
        )

    return app


def _validate_limits(request: ClassifyRequest, settings: Settings) -> None:
    """Enforce the batch, size and uniqueness bounds.

    Ids must be unique because the gateway maps results back by id: a duplicate
    would silently overwrite another field's score.
    """
    if len(request.items) > settings.max_items:
        raise HTTPException(
            status_code=HTTP_UNPROCESSABLE_CONTENT,
            detail=(
                f"{len(request.items)} items exceeds the batch limit of "
                f"{settings.max_items}"
            ),
        )

    seen: set[str] = set()
    total = 0
    for item in request.items:
        if item.id in seen:
            raise HTTPException(
                status_code=HTTP_UNPROCESSABLE_CONTENT,
                detail=f"duplicate item id {item.id!r}",
            )
        seen.add(item.id)

        size = len(item.text.encode("utf-8"))
        if size > settings.max_text_bytes:
            raise HTTPException(
                status_code=HTTP_CONTENT_TOO_LARGE,
                detail=(
                    f"item {item.id!r} is {size} bytes, above the per-item limit of "
                    f"{settings.max_text_bytes}"
                ),
            )
        total += size

    if total > settings.max_total_bytes:
        raise HTTPException(
            status_code=HTTP_CONTENT_TOO_LARGE,
            detail=(
                f"the request carries {total} bytes of text, above the limit of "
                f"{settings.max_total_bytes}"
            ),
        )


app_factory = create_app


# The ASGI application uvicorn is pointed at. Built at import time so a
# configuration error surfaces on startup rather than on the first request.
app = create_app()
