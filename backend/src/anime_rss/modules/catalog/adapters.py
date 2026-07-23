import re
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
    airing_weekday: int | None = None
    airing_time: str | None = None
    platform: str | None = None
    popularity: int = 0
    rating_score: float | None = None
    rating_total: int = 0


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

    def list_season(self, start_date: str, end_date: str) -> list[BangumiAnime]:
        items: list[BangumiAnime] = []
        offset = 0
        limit = 50
        while offset < 200:
            try:
                response = self._client.post(
                    "/v0/search/subjects",
                    params={"limit": limit, "offset": offset},
                    json={
                        "keyword": "",
                        "sort": "rank",
                        "filter": {
                            "type": [2],
                            "air_date": [f">={start_date}", f"<{end_date}"],
                        },
                    },
                )
                response.raise_for_status()
                raw_payload: object = response.json()
            except (httpx.HTTPError, ValueError) as error:
                raise CatalogProviderError("bangumi_unavailable") from error
            if not isinstance(raw_payload, dict):
                raise CatalogProviderError("bangumi_invalid_response")
            payload = cast(dict[str, object], raw_payload)
            raw_data = payload.get("data")
            if not isinstance(raw_data, list):
                raise CatalogProviderError("bangumi_invalid_response")
            typed_data = cast(list[object], raw_data)
            page = [
                self._from_payload(cast(dict[str, Any], item))
                for item in typed_data
                if isinstance(item, dict)
            ]
            items.extend(item for item in page if item.platform in {"TV", "WEB"})
            total = payload.get("total")
            offset += len(typed_data)
            if not typed_data or not isinstance(total, int) or offset >= total:
                break
        unique = {item.bangumi_id: item for item in items}
        return sorted(
            unique.values(),
            key=lambda item: (-item.popularity, item.air_date or "9999-99-99", item.name),
        )

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
        airing_weekday: int | None = None
        airing_time: str | None = None
        infobox_value: object = payload.get("infobox")
        if isinstance(infobox_value, list):
            infobox = cast(list[object], infobox_value)
            for item in infobox:
                if not isinstance(item, dict):
                    continue
                typed_item = cast(dict[str, object], item)
                key = typed_item.get("key")
                value = typed_item.get("value")
                if key in {"放送星期", "播放星期"}:
                    airing_weekday = BangumiClient._parse_weekday(value)
                    continue
                if key in {"放送开始", "播放开始", "首播"}:
                    airing_time = BangumiClient._parse_time(value)
                    continue
                if key not in {"别名", "別名"}:
                    continue
                values = cast(list[object], value) if isinstance(value, list) else [value]
                for raw_alias in values:
                    alias: object = raw_alias
                    if isinstance(alias, dict):
                        alias = cast(dict[str, object], alias).get("v")
                    if isinstance(alias, str) and alias.strip():
                        aliases.append(alias.strip())
        collection_value: object = payload.get("collection")
        collection = (
            cast(dict[str, object], collection_value) if isinstance(collection_value, dict) else {}
        )
        wish = collection.get("wish")
        doing = collection.get("doing")
        popularity = (wish if isinstance(wish, int) else 0) + (
            doing if isinstance(doing, int) else 0
        )
        rating_value: object = payload.get("rating")
        rating = cast(dict[str, object], rating_value) if isinstance(rating_value, dict) else {}
        score = rating.get("score")
        total = rating.get("total")
        rating_score = (
            float(score)
            if isinstance(score, int | float) and not isinstance(score, bool) and 0 < score <= 10
            else None
        )
        rating_total = (
            total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else 0
        )
        return BangumiAnime(
            bangumi_id=bangumi_id,
            name=name.strip(),
            name_cn=name_cn.strip() if isinstance(name_cn, str) and name_cn.strip() else None,
            summary=(str(payload["summary"])[:4000] if payload.get("summary") else None),
            air_date=(str(payload["date"])[:10] if payload.get("date") else None),
            episode_count=(payload.get("eps") if isinstance(payload.get("eps"), int) else None),
            cover_url=cover_url if isinstance(cover_url, str) else None,
            aliases=tuple(dict.fromkeys(aliases)),
            airing_weekday=airing_weekday,
            airing_time=airing_time,
            platform=(
                str(payload["platform"])[:24]
                if isinstance(payload.get("platform"), str) and payload["platform"]
                else None
            ),
            popularity=popularity,
            rating_score=rating_score,
            rating_total=rating_total,
        )

    @staticmethod
    def _parse_weekday(value: object) -> int | None:
        if isinstance(value, list) and value:
            value = cast(list[object], value)[0]
        if isinstance(value, dict):
            value = cast(dict[str, object], value).get("v")
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        names = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        for name, weekday in names.items():
            if name in normalized:
                return weekday
        return None

    @staticmethod
    def _parse_time(value: object) -> str | None:
        if isinstance(value, list) and value:
            value = cast(list[object], value)[0]
        if isinstance(value, dict):
            value = cast(dict[str, object], value).get("v")
        if not isinstance(value, str):
            return None
        match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", value)
        if match is None:
            return None
        return f"{int(match.group(1)):02d}:{match.group(2)}"
