"""Shared sync/async contracts for failure evidence and safe diagnostics."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

import zend
import zend.client
from zend import (
    APIError,
    ApplicationError,
    AsyncZend,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ResponseValidationError,
    ServerError,
    TransportError,
    Zend,
    ZendFailure,
    ZendSuccess,
    ZendTimeoutError,
)
from zend.client.http_client import AsyncHttpClient, HttpClient
from zend.resources.emails.types import Email

SENSITIVE = "https://private.test/recipient@example.com?key=secret-key"


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def asynchronous(request) -> bool:
    return request.param


async def request_with(asynchronous: bool, handler, cast_to: Any = Email):
    kwargs = dict(
        api_key="secret-key",
        base_url="https://private.test",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )
    if asynchronous:
        client = AsyncHttpClient(**kwargs)
        try:
            return await client.request("POST", SENSITIVE, cast_to=cast_to)
        finally:
            await client.aclose()
    client = HttpClient(**kwargs)
    try:
        return client.request("POST", SENSITIVE, cast_to=cast_to)
    finally:
        client.close()


def assert_safe(error) -> None:
    for diagnostic in (str(error), repr(error), repr(vars(error)), repr(error.args)):
        for secret in (SENSITIVE, "recipient@example.com", "secret-key"):
            assert secret not in diagnostic
    assert set(vars(error)) == {"name", "status_code", "code"}
    assert error.code is None
    assert error.__cause__ is None
    assert error.__context__ is None


async def test_valid_success(asynchronous) -> None:
    res = await request_with(
        asynchronous, lambda _: httpx.Response(201, json={"_id": "e1", "__v": 0})
    )
    assert isinstance(res, ZendSuccess)
    assert res.unwrap().id == "e1"


@pytest.mark.parametrize("status", [200, 201, 202, 299])
@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b'{"id":',
        b'"recipient@example.com"',
        b"{}",
        b'{"id": {"private": "secret-key"}}',
        b"null",
    ],
)
async def test_response_interpretation_failure(asynchronous, status, body) -> None:
    res = await request_with(
        asynchronous,
        lambda _: httpx.Response(status, content=body, headers={"X-Private": SENSITIVE}),
    )
    assert isinstance(res, ZendFailure)
    assert isinstance(res.error, ResponseValidationError)
    assert isinstance(res.error, ApplicationError)
    assert res.error.status_code == status
    assert_safe(res.error)
    with pytest.raises(ApplicationError) as caught:
        res.unwrap()
    assert caught.value is res.error


@pytest.mark.parametrize("cast_to", [None, TypeAdapter(Email | None)])
async def test_malformed_json_is_not_confused_with_null(asynchronous, cast_to) -> None:
    res = await request_with(asynchronous, lambda _: httpx.Response(200, text=SENSITIVE), cast_to)
    assert isinstance(res.error, ResponseValidationError)
    assert_safe(res.error)


@pytest.mark.parametrize("cast_to", [None, TypeAdapter(Email | None)])
@pytest.mark.parametrize("status", [200, 204])
async def test_supported_empty_body(asynchronous, cast_to, status) -> None:
    res = await request_with(asynchronous, lambda _: httpx.Response(status), cast_to)
    assert isinstance(res, ZendSuccess)
    assert res.data is None


async def test_empty_body_with_required_schema(asynchronous) -> None:
    res = await request_with(asynchronous, lambda _: httpx.Response(200))
    assert isinstance(res.error, ResponseValidationError)
    assert res.error.status_code == 200


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.CloseError,
        httpx.RemoteProtocolError,
        httpx.LocalProtocolError,
        httpx.ProxyError,
        httpx.UnsupportedProtocol,
        httpx.DecodingError,
        httpx.TooManyRedirects,
    ],
)
async def test_transport_failure(asynchronous, exception) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        raise exception(SENSITIVE, request=request)

    res = await request_with(asynchronous, handler)
    assert isinstance(res, ZendFailure)
    assert isinstance(res.error, TransportError)
    assert isinstance(res.error, ApplicationError)
    assert res.error.status_code is None
    assert_safe(res.error)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "exception",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
async def test_timeout_contract(asynchronous, exception) -> None:
    def handler(request):
        raise exception(SENSITIVE, request=request)

    res = await request_with(asynchronous, handler)
    assert isinstance(res.error, ZendTimeoutError)
    assert not isinstance(res.error, ApplicationError)
    assert res.error.status_code is None
    assert res.error.name == "timeout"
    assert str(res.error) == "Request timed out after 5000ms"
    assert_safe(res.error)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (302, APIError),
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, APIError),
        (422, APIError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
    ],
)
@pytest.mark.parametrize("json_body", [True, False], ids=["json", "non-json"])
async def test_http_rejections(asynchronous, status, error_type, json_body) -> None:
    def handler(_):
        if json_body:
            return httpx.Response(status, json={"message": "Rejected", "code": "provider-code"})
        return httpx.Response(status, text="Rejected")

    res = await request_with(asynchronous, handler)
    assert isinstance(res, ZendFailure)
    assert type(res.error) is error_type
    assert res.error.status_code == status
    assert str(res.error) == "Rejected"
    assert res.error.code == ("provider-code" if json_body else None)


async def test_request_validation_still_raises_before_submission(asynchronous) -> None:
    def handler(_):
        pytest.fail("Invalid arguments must not reach HTTP submission")

    kwargs = dict(api_key="k", transport=httpx.MockTransport(handler))
    if asynchronous:
        async with AsyncZend(**kwargs) as client:
            with pytest.raises(ValidationError):
                await client.emails.send(to="recipient@example.com")
    else:
        with Zend(**kwargs) as client:
            with pytest.raises(ValidationError):
                client.emails.send(to="recipient@example.com")


def test_public_exports() -> None:
    for name in ("TransportError", "ResponseValidationError"):
        assert getattr(zend, name) is getattr(zend.client, name)
        assert name in zend.__all__
        assert name in zend.client.__all__
