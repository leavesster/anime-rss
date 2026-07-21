from dataclasses import asdict, dataclass

import httpx


class WebhookError(RuntimeError):
    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


@dataclass(frozen=True, slots=True)
class WebhookMessage:
    id: str
    kind: str
    level: str
    title: str
    message: str
    entity_type: str | None
    entity_id: str | None
    created_at: str


class WebhookClient:
    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=read_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def deliver(
        self,
        *,
        url: str,
        bearer_token: str | None,
        message: WebhookMessage,
    ) -> None:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "anime-rss-service/0.1",
            "Idempotency-Key": message.id,
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        try:
            response = self._client.post(url, headers=headers, json=asdict(message))
        except httpx.TimeoutException as error:
            raise WebhookError("webhook_timeout", transient=True) from error
        except httpx.NetworkError as error:
            raise WebhookError("webhook_network_error", transient=True) from error
        if response.status_code in {401, 403}:
            raise WebhookError("webhook_authentication_failed", transient=False)
        if response.status_code == 429 or response.status_code >= 500:
            raise WebhookError("webhook_unavailable", transient=True)
        if response.status_code < 200 or response.status_code >= 300:
            raise WebhookError("webhook_rejected", transient=False)
