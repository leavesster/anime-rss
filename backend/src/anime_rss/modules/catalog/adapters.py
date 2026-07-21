from dataclasses import dataclass
from typing import Any, cast

import httpx


class CatalogProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BangumiAnime:
    bangumi_id: int
    name: str
    name_cn: str | None
    summary: str | None
    air_date: str | None
    episode_count: int | None
    cover_url: str | None
    aliases: tuple[str, ...] = ()


class BangumiClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url="https://api.bgm.tv",
            headers={
                "Accept": "application/json",
                "User-Agent": "anime-rss-service/0.1",
            },
            timeout=httpx.Timeout(10.0, read=20.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, *, limit: int = 12) -> list[BangumiAnime]:
        try:
            response = self._client.post(
                "/v0/search/subjects",
                params={"limit": min(max(limit, 1), 20)},
                json={"keyword": query, "filter": {"type": [2]}},
            )
            response.raise_for_status()
            raw_payload: object = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise CatalogProviderError("bangumi_unavailable") from error
        if not isinstance(raw_payload, dict):
            raise CatalogProviderError("bangumi_invalid_response")
        payload = cast(dict[str, object], raw_payload)
        raw_data_value = payload.get("data", [])
        if not isinstance(raw_data_value, list):
            raise CatalogProviderError("bangumi_invalid_response")
        raw_data = cast(list[object], raw_data_value)
        return [
            self._from_payload(cast(dict[str, Any], item))
            for item in raw_data
            if isinstance(item, dict)
        ]

    def get(self, bangumi_id: int) -> BangumiAnime:
        try:
            response = self._client.get(f"/v0/subjects/{bangumi_id}")
            response.raise_for_status()
            raw_payload: object = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise CatalogProviderError("bangumi_unavailable") from error
        if not isinstance(raw_payload, dict):
            raise CatalogProviderError("bangumi_invalid_response")
        return self._from_payload(cast(dict[str, Any], raw_payload))

    @staticmethod
    def _from_payload(payload: dict[str, Any]) -> BangumiAnime:
        bangumi_id = payload.get("id")
        name = payload.get("name")
        if not isinstance(bangumi_id, int) or not isinstance(name, str) or not name.strip():
            raise CatalogProviderError("bangumi_invalid_response")
        name_cn = payload.get("name_cn")
        images_value: object = payload.get("images")
        images = cast(dict[str, object], images_value) if isinstance(images_value, dict) else None
        cover_url: object = images.get("large") if images is not None else None
        aliases: list[str] = []
        infobox_value: object = payload.get("infobox")
        if isinstance(infobox_value, list):
            infobox = cast(list[object], infobox_value)
            for item in infobox:
                if not isinstance(item, dict):
                    continue
                typed_item = cast(dict[str, object], item)
                if typed_item.get("key") not in {"别名", "別名"}:
                    continue
                value = typed_item.get("value")
                values = cast(list[object], value) if isinstance(value, list) else [value]
                for raw_alias in values:
                    alias: object = raw_alias
                    if isinstance(alias, dict):
                        alias = cast(dict[str, object], alias).get("v")
                    if isinstance(alias, str) and alias.strip():
                        aliases.append(alias.strip())
        return BangumiAnime(
            bangumi_id=bangumi_id,
            name=name.strip(),
            name_cn=name_cn.strip() if isinstance(name_cn, str) and name_cn.strip() else None,
            summary=(str(payload["summary"])[:4000] if payload.get("summary") else None),
            air_date=(str(payload["date"])[:10] if payload.get("date") else None),
            episode_count=(payload.get("eps") if isinstance(payload.get("eps"), int) else None),
            cover_url=cover_url if isinstance(cover_url, str) else None,
            aliases=tuple(dict.fromkeys(aliases)),
        )
