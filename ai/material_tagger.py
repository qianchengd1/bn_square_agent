from __future__ import annotations

import re
from dataclasses import dataclass, asdict


TOKEN_RE = re.compile(
    r"(?:\{future\}\(([A-Z0-9]{2,20}USDT)\))|\$([A-Z][A-Z0-9]{1,20})|([A-Z0-9]{2,20}USDT)"
)

TOKEN_ALIASES = (
    ("BTC", ("BTC", "比特币", "Bitcoin")),
    ("ETH", ("ETH", "以太坊", "Ethereum")),
    ("BNB", ("BNB", "币安币", "BNB Chain")),
    ("SOL", ("SOL", "Solana")),
    ("XRP", ("XRP", "Ripple")),
    ("DOGE", ("DOGE", "Dogecoin")),
    ("ADA", ("ADA", "Cardano")),
    ("ZEC", ("ZEC", "Zcash")),
    ("ONDO", ("ONDO", "Ondo")),
    ("PYTH", ("PYTH", "Pyth")),
    ("UNI", ("UNI", "Uniswap")),
    ("LINK", ("LINK", "Chainlink")),
    ("MANTA", ("MANTA", "Manta")),
)


@dataclass(frozen=True)
class MaterialTag:
    accepted: bool
    token: str | None
    symbol: str | None
    direction: str
    has_chart_symbol: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class MaterialTagger:
    def tag(self, *, title: str | None, content: str) -> MaterialTag:
        text = f"{title or ''}\n{content}".strip()
        token, symbol = self._extract_token(text)
        direction = self._extract_direction(text)
        reasons: list[str] = []

        if not text:
            reasons.append("empty_content")
        if not token:
            reasons.append("missing_token")
        if direction == "unknown":
            reasons.append("missing_direction")

        accepted = bool(text and token)
        if accepted:
            reasons.append("ready_for_auto_consume")

        return MaterialTag(
            accepted=accepted,
            token=token,
            symbol=symbol,
            direction=direction,
            has_chart_symbol=bool(symbol),
            reasons=reasons,
        )

    def _extract_token(self, text: str) -> tuple[str | None, str | None]:
        for match in TOKEN_RE.finditer(text):
            futures_symbol, cash_token, plain_symbol = match.groups()
            if futures_symbol:
                return futures_symbol.removesuffix("USDT"), futures_symbol
            if plain_symbol:
                return plain_symbol.removesuffix("USDT"), plain_symbol
            if cash_token:
                token = cash_token.upper()
                return token, f"{token}USDT"
        alias_match = self._find_first_alias(text)
        if alias_match:
            return alias_match, f"{alias_match}USDT"
        return None, None

    @staticmethod
    def _alias_index(text: str, alias: str) -> int | None:
        if re.fullmatch(r"[A-Za-z0-9]+", alias):
            match = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                text,
                re.I,
            )
            return match.start() if match else None
        index = text.find(alias)
        return index if index >= 0 else None

    def _find_first_alias(self, text: str) -> str | None:
        matches: list[tuple[int, str]] = []
        for token, aliases in TOKEN_ALIASES:
            indexes = [
                index
                for alias in aliases
                if (index := self._alias_index(text, alias)) is not None
            ]
            if indexes:
                matches.append((min(indexes), token))
        if not matches:
            return None
        return min(matches, key=lambda item: item[0])[1]

    def _extract_direction(self, text: str) -> str:
        short_patterns = (
            "看空",
            "做空",
            "开空",
            "空进",
            "空！",
            "空!",
            "空了",
            "继续空",
        )
        long_patterns = (
            "看多",
            "做多",
            "开多",
            "接多",
            "抄底",
            "多！",
            "多!",
            "多进",
            "继续多",
        )
        if any(word in text for word in short_patterns):
            return "short"
        if any(word in text for word in long_patterns):
            return "long"
        return "unknown"
