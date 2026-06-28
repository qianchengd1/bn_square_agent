from __future__ import annotations

from dataclasses import dataclass
import base64
import re
from typing import Literal


MarketKind = Literal["future", "spot"]


@dataclass(frozen=True)
class ChartTarget:
    symbol: str
    market: MarketKind


class ChartImageService:
    def __init__(self, *, timeout_ms: int = 60_000):
        self.timeout_ms = timeout_ms

    @staticmethod
    def extract_target(text: str) -> ChartTarget | None:
        explicit_future = re.search(
            r"\{future\}\(([A-Z0-9]{2,30}USDT)\)",
            text,
            re.IGNORECASE,
        )
        if explicit_future:
            return ChartTarget(explicit_future.group(1).upper(), "future")

        symbol_pair = re.search(r"\b([A-Z0-9]{2,30}USDT)\b", text)
        if symbol_pair:
            return ChartTarget(symbol_pair.group(1).upper(), "future")

        cashtag = re.search(r"\$([A-Z][A-Z0-9]{0,14})\b", text)
        if cashtag:
            token = cashtag.group(1).upper()
            if token not in {"USD", "USDT"}:
                return ChartTarget(f"{token}USDT", "future")
        return None

    @staticmethod
    def chart_url(target: ChartTarget) -> str:
        if target.market == "future":
            return f"https://www.binance.com/zh-CN/futures/{target.symbol}"
        base = target.symbol.removesuffix("USDT")
        return f"https://www.binance.com/zh-CN/trade/{base}_USDT"

    def image_for_text(self, text: str) -> str | None:
        target = self.extract_target(text)
        if not target:
            return None
        return self.capture_chart(target)

    def capture_chart(self, target: ChartTarget) -> str | None:
        from playwright.sync_api import sync_playwright

        url = self.chart_url(target)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(8000)
            for selector in (
                "[data-testid='kline-chart']",
                ".chart-widget",
                ".tradingview-widget-container",
                "canvas",
            ):
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.bounding_box():
                        png = locator.screenshot(type="png", timeout=10_000)
                        browser.close()
                        return "data:image/png;base64," + base64.b64encode(png).decode(
                            "ascii"
                        )
                except Exception:
                    continue
            png = page.screenshot(type="png", full_page=False)
            browser.close()
            return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
