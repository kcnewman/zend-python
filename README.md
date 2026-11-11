# zend-python

> **Note:** This is an unofficial, independently maintained Python SDK. It is not
> developed, endorsed, or supported by Zend.

Experimental Python client for the [Zend](https://tryzend.dev) messaging platform. Send SMS, WhatsApp, email, and voice messages — and manage message templates — from a single, typed client.

The public API follows Zend's official [Node](https://github.com/usezend/zend-node)
and [Go](https://github.com/usezend/zend-go) SDKs while using Python-native sync
and async clients.

📚 **[Read the docs →](https://tryzend.com/docs)**

## Installation

This package is not published on PyPI. Install it directly from the repository:

```bash
pip install "git+https://github.com/oo7kc/zend-python.git"
```

Or install a local clone:

```bash
git clone https://github.com/oo7kc/zend-python.git
cd zend-python
pip install .
```

For development, include the test, lint, type-checking, and build tools:

```bash
pip install -e ".[dev]"
```

Requires Python 3.10 or later.

## Usage

Create a client with your API key:

```python
from zend import Zend

zend = Zend("sent_live_...")
```

The API key can also be supplied via the `ZEND_API_KEY` environment variable:

```python
zend = Zend()
```

Override the base URL or request timeout — or set `ZEND_BASE_URL`:

```python
zend = Zend(
    "sent_live_...",
    base_url="https://staging.api.tryzend.com",
    timeout=30.0,  # seconds
)
```

> **Timeouts are in seconds** (default `30.0`).  
> `base_url` defaults to `https://api.tryzend.com`.

Prefer a context manager so the underlying HTTP connection pool is closed cleanly:

```python
with Zend("sent_live_...") as zend:
    result = zend.messages.send(to="+233201234567", body="Hello!")
```

Every API call returns a typed success/failure `ZendResponse` — see [Errors](#errors) below.

### Async client

```python
from zend import AsyncZend

async with AsyncZend("sent_live_...") as zend:
    result = await zend.messages.send(to="+233201234567", body="Hello from Zend!")
    sms = result.unwrap()
    print(sms.id)
```

## Send SMS / WhatsApp

```python
sms = zend.messages.send(
    to="+233201234567",
    body="Hello from Zend!",
    preferred_channels=["sms"],
    sender_id="MyBrand",
    fallback_enabled=True,
    priority="high",
    delivery_priority="speed",
    webhook_url="https://your-app.com/webhooks/zend",
)

message = sms.unwrap()
print(f"Message {message.id} ({message.status})")
```

WhatsApp with a template, falling back to SMS:

```python
zend.messages.send(
    to="+233201234567",
    template_id="welcome",
    template_params={"first_name": "John"},
    preferred_channels=["whatsapp", "sms"],
    fallback_enabled=True,
    sender_id="MyBrand",
)
```

Bulk send:

```python
zend.messages.send_bulk(
    messages=[
        {"to": "+233201234567", "body": "Hi Ama!"},
        {
            "to": "+233207654321",
            "body": "Your code is 123456",
            "template_params": {"code": "123456"},
        },
    ],
    preferred_channels=["sms"],
    sender_id="MyBrand",
    fallback_enabled=True,
    webhook_url="https://your-app.com/webhooks/zend",
)
```

Other `messages` methods: `get(id)`, `list(params?)`, `cancel(id)`, `retry(id)`.

## Send Email

```python
email = zend.emails.send(
    from_="you@example.com",
    to="user@gmail.com",
    subject="Hello world",
    html="<p>It works!</p>",
    text="It works!",
)

sent_email = email.unwrap()
print(f"Email {sent_email.id} sent")
```

The email sender argument is named `from_` because `from` is a Python keyword.

Attachments — `content` is `bytes` or a base64 string:

```python
zend.emails.send(
    from_="you@example.com",
    to="user@gmail.com",
    subject="Your invoice",
    html="<p>Invoice attached.</p>",
    attachments=[
        {"filename": "invoice.pdf", "content": pdf_bytes, "content_type": "application/pdf"}
    ],
)
```

Other `emails` methods: `get(id)`, `list(params?)`.

## Send Voice

```python
zend.voice.send(
    recipients=["+233201234567"],
    text="Your order has shipped.",
    voice="female",
    retry=True,
    callback_url="https://your-app.com/webhooks/voice",
    fallback={
        "sms": True,
        "sms_text": "Your order has shipped.",
        "sender_id": "MyBrand",
    },
)
```

Upload a local audio file, then pass the returned URL:

```python
uploaded = zend.voice.upload(open("message.mp3", "rb"), "message.mp3")
voice_file = uploaded.unwrap()
zend.voice.send(recipients=["+233201234567"], voice_url=voice_file.url)
```

Other `voice` methods: `get(batch_id)`, `list(params?)`.

## Templates

```python
templates = zend.templates.list(
    category="transactional",
    status="active",
    limit=20,
    offset=0,
).unwrap()
print(f"You have {templates.total} templates")

template = zend.templates.get("welcome").unwrap()
print(template.name)
```

## Errors

API and network failures are returned rather than raised. The result is always one of:

```python
ZendSuccess(data=T, error=None) | ZendFailure(data=None, error=ZendError)
```

```python
sms = zend.messages.send(to="+233201234567", body="Hello!")

if sms.error is not None:
    raise sms.error

print(sms.data.id)
```

Alternatively, `sms.unwrap()` returns the successful data or raises the contained
`ZendError`.

Invalid method arguments are programmer errors and raise Pydantic's
`ValidationError`. Passing both an options model and keyword arguments raises
`TypeError`.

`ZendError` subclasses include `APIError`, `BadRequestError`, `AuthenticationError`,
`PermissionDeniedError`, `NotFoundError`, `RateLimitError`, `ServerError`,
`ZendTimeoutError`, and `ApplicationError`. Attributes:

- `name` — e.g. `"api_error"`, `"timeout"`, `"application_error"`
- `status_code` — HTTP status when available
- `code` — provider error code when available

Transport and success-response interpretation failures have distinct types:

```python
from zend import ResponseValidationError, TransportError, ZendTimeoutError

result = zend.emails.send(
    from_="you@example.com",
    to="user@example.com",
    subject="Hello",
    html="<p>Hello!</p>",
)
error = result.error
if isinstance(error, ResponseValidationError):
    # A 2xx response arrived, but JSON decoding or schema validation failed.
    print("Unusable success response", error.status_code)
elif isinstance(error, (TransportError, ZendTimeoutError)):
    # No usable HTTP response was received; status_code is None.
    print("No usable response")
elif error is not None:
    # Existing HTTP rejection types and provider error details still apply.
    print(error.name, error.status_code)
else:
    email = result.unwrap()
```

`TransportError` and `ResponseValidationError` subclass `ApplicationError`, so
existing `isinstance(error, ApplicationError)` checks continue to work.
`ZendTimeoutError` retains its separate inheritance from `ZendError` and its
existing timeout message. The new errors use stable messages rather than raw
transport or validation details; callers should branch on types and attributes.
`ResponseValidationError.status_code` retains the received 2xx status.
Nonempty malformed JSON is a failure even for untyped or nullable responses;
empty bodies still succeed when the expected response type permits `None`.

Neither a transport failure (including a timeout) nor an unusable success response
proves whether the provider performed the operation. These categories do not
establish acceptance or delivery. Applications remain responsible for retry,
reconciliation, and duplicate-send policies. The SDK adds no automatic retries
or retry-safety flag; provider-side idempotency is outside this behavior.

No provider request/correlation ID header convention could be verified in Zend's
[error documentation](https://www.tryzend.com/docs/platform/errors) or
[SDK documentation](https://www.tryzend.com/docs/sdks/node). The SDK therefore
does not guess a header or expose a request ID. The new diagnostics retain no
complete headers, bodies, credentials, recipient details, request URLs, or raw
exceptions.

## Full example

See [`examples/quickstart.py`](./examples/quickstart.py) for a complete walkthrough.
