from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter

from zend.client.error import (
    ResponseValidationError,
    TransportError,
    ZendError,
    ZendTimeoutError,
)
from zend.common.normalize import normalize_response
from zend.common.types import ZendFailure, ZendResponse, ZendSuccess
from zend.version import VERSION

T = TypeVar("T")


def _dump_body(body: Any) -> Any:
    """Serialize a request body to snake_case wire JSON.

    Pydantic models dump with aliases where set (e.g. ``from_`` → ``from``).
    Nested maps such as ``template_params`` keep caller key casing as-is —
    Pydantic leaves ``dict[str, Any]`` values untouched.
    """
    if isinstance(body, BaseModel):
        data = body.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(body, dict):
        data = {k: v for k, v in body.items() if v is not None}
    else:
        return body

    return data


def _parse_json(response: httpx.Response) -> Any:
    text = response.text
    if not text:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _cast(data: Any, cast_to: type[T] | TypeAdapter[T] | None) -> T:
    if cast_to is None:
        return data
    if isinstance(cast_to, TypeAdapter):
        return cast_to.validate_python(data)
    if isinstance(cast_to, type) and issubclass(cast_to, BaseModel):
        return cast_to.model_validate(data)
    return TypeAdapter(cast_to).validate_python(data)


def _handle_response(
    response: httpx.Response,
    cast_to: type[T] | TypeAdapter[T] | None,
) -> ZendResponse[T]:
    if not 200 <= response.status_code < 300:
        return ZendFailure(
            error=ZendError.from_http(
                response.status_code,
                _parse_json(response),
                response.text,
                response.reason_phrase,
            )
        )

    try:
        # Empty responses remain supported when the expected type permits None.
        # Nonempty bodies must be JSON, even for untyped/nullable responses.
        json_body = response.json() if response.content else None
        data = _cast(normalize_response(json_body), cast_to)
    except (TypeError, ValueError):
        return ZendFailure(error=ResponseValidationError(status_code=response.status_code))
    return ZendSuccess(data=data)


class HttpClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
                "User-Agent": f"usezend-python/{VERSION}",
                **(headers or {}),
            },
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        files: Any = None,
        cast_to: type[T] | TypeAdapter[T] | None = None,
    ) -> ZendResponse[T]:
        params = None
        if query:
            params = {k: v for k, v in query.items() if v is not None}

        kwargs: dict[str, Any] = {"method": method, "url": path, "params": params}
        if files is not None:
            kwargs["files"] = files
        elif json_body is not None:
            kwargs["json"] = _dump_body(json_body)

        try:
            response = self._client.request(**kwargs)
        except httpx.TimeoutException:
            return ZendFailure(
                error=ZendTimeoutError(f"Request timed out after {int(self._timeout * 1000)}ms"),
            )
        except httpx.HTTPError:
            return ZendFailure(error=TransportError())

        return _handle_response(response, cast_to)


class AsyncHttpClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
                "User-Agent": f"usezend-python/{VERSION}",
                **(headers or {}),
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        files: Any = None,
        cast_to: type[T] | TypeAdapter[T] | None = None,
    ) -> ZendResponse[T]:
        params = None
        if query:
            params = {k: v for k, v in query.items() if v is not None}

        kwargs: dict[str, Any] = {"method": method, "url": path, "params": params}
        if files is not None:
            kwargs["files"] = files
        elif json_body is not None:
            kwargs["json"] = _dump_body(json_body)

        try:
            response = await self._client.request(**kwargs)
        except httpx.TimeoutException:
            return ZendFailure(
                error=ZendTimeoutError(f"Request timed out after {int(self._timeout * 1000)}ms"),
            )
        except httpx.HTTPError:
            return ZendFailure(error=TransportError())

        return _handle_response(response, cast_to)
