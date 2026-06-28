from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from ..storage.database import Database


BINANCE_BASE_URL = "https://www.binance.com"
USER_CLIENT_API = "/bapi/composite/v3/friendly/pgc/user/client"
PROFILE_CONTENTS_API = (
    "/bapi/composite/v2/friendly/pgc/content/queryUserProfilePageContentsWithFilter"
)


@dataclass(frozen=True)
class MaterialArticle:
    title: str | None
    content: str
    author: str | None = None
    url: str | None = None
    external_id: str | None = None
    source_created_at: str | None = None


class BinanceSquareMonitor:
    def __init__(self, *, timeout_ms: int = 60_000, max_pages: int = 3):
        self.timeout_ms = timeout_ms
        self.max_pages = max_pages

    @staticmethod
    def _username_from_url(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        match = re.search(r"/square/profile/([^/]+)$", path, re.IGNORECASE)
        if not match:
            raise ValueError("素材源 URL 必须是 BN 广场作者主页，例如 /square/profile/xxx")
        return match.group(1)

    @staticmethod
    def _ms_to_iso(value: Any) -> str | None:
        if not isinstance(value, int):
            return None
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()

    @staticmethod
    def _article_from_content(item: dict[str, Any]) -> MaterialArticle | None:
        content = str(item.get("bodyTextOnly") or "").strip()
        if len(content) < 20:
            return None
        content_id = item.get("id")
        title = str(item.get("title") or "").strip() or None
        if not title:
            title = content[:48]
        return MaterialArticle(
            title=title,
            content=content,
            author=str(item.get("displayName") or item.get("username") or "").strip()
            or None,
            url=item.get("webLink"),
            external_id=str(content_id) if content_id is not None else None,
            source_created_at=BinanceSquareMonitor._ms_to_iso(
                item.get("firstReleaseTime") or item.get("createTime")
            ),
        )

    def fetch(self, url: str) -> list[MaterialArticle]:
        username = self._username_from_url(url)
        return self._fetch_with_playwright(username)

    def _fetch_with_playwright(self, username: str) -> list[MaterialArticle]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            profile_url = f"{BINANCE_BASE_URL}/zh-CN/square/profile/{username}"
            page.goto(profile_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(3000)

            user_result = page.evaluate(
                """async ({api, username}) => {
                    const response = await fetch(api, {
                        method: 'POST',
                        credentials: 'include',
                        headers: {'content-type': 'application/json'},
                        body: JSON.stringify({
                            username,
                            getFollowCount: true,
                            queryFollowersInfo: true,
                            queryRelationTokens: true
                        })
                    });
                    return await response.json();
                }""",
                {"api": USER_CLIENT_API, "username": username},
            )
            data = user_result.get("data") or {}
            square_uid = data.get("squareUid")
            if not square_uid:
                browser.close()
                raise ValueError(f"无法解析作者 squareUid: {user_result}")

            articles: list[MaterialArticle] = []
            seen_ids: set[str] = set()
            time_offset: int | str = -1
            for _ in range(self.max_pages):
                contents_result = page.evaluate(
                    """async ({api, squareUid, timeOffset}) => {
                        const params = new URLSearchParams({
                            targetSquareUid: squareUid,
                            timeOffset: String(timeOffset),
                            filterType: 'ALL'
                        });
                        const response = await fetch(`${api}?${params}`, {
                            credentials: 'include'
                        });
                        return await response.json();
                    }""",
                    {
                        "api": PROFILE_CONTENTS_API,
                        "squareUid": square_uid,
                        "timeOffset": time_offset,
                    },
                )
                contents_data = contents_result.get("data") or {}
                contents = contents_data.get("contents") or []
                if not contents:
                    break
                for item in contents:
                    article = self._article_from_content(item)
                    if not article:
                        continue
                    key = article.external_id or article.content[:120]
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    articles.append(article)
                next_offset = contents_data.get("timeOffset")
                if not next_offset or next_offset == time_offset:
                    break
                time_offset = next_offset
            browser.close()
            return articles


class MaterialSourceService:
    def __init__(self, db: Database):
        self.db = db
        self.binance_square = BinanceSquareMonitor()

    def check_source(self, source: dict[str, Any]) -> dict[str, Any]:
        if source["source_type"] != "binance_square":
            raise ValueError(f"不支持的素材源类型: {source['source_type']}")
        try:
            articles = self.binance_square.fetch(source["url"])
            inserted = 0
            for article in articles:
                _, fresh = self.db.add_material_item(
                    source_id=source["id"],
                    external_id=article.external_id,
                    author=article.author,
                    title=article.title,
                    content=article.content,
                    url=article.url,
                    source_created_at=article.source_created_at,
                )
                inserted += 1 if fresh else 0
            self.db.update_material_source_check(source["id"])
            return {"source_id": source["id"], "found": len(articles), "inserted": inserted}
        except Exception as exc:
            self.db.update_material_source_check(source["id"], error=str(exc))
            return {"source_id": source["id"], "found": 0, "inserted": 0, "error": str(exc)}

    def check_all(self) -> list[dict[str, Any]]:
        return [self.check_source(source) for source in self.db.list_material_sources()]
