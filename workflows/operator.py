from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from ..core.config import AccountConfig
from ..storage.database import Database
from ..publishing.publisher import PublishingService, PublishResult


@dataclass
class AccountContentRun:
    account_key: str
    generated_ids: list[int] = field(default_factory=list)
    approved_generated_id: int | None = None
    publish_result: PublishResult | None = None
    error: str | None = None


class MultiAccountOperator:
    def __init__(
        self,
        *,
        db: Database,
        accounts: tuple[AccountConfig, ...],
        content_graph: Any,
        publishing_service: PublishingService | None = None,
        auto_publish: bool = True,
    ):
        self.db = db
        self.accounts = accounts
        self.content_graph = content_graph
        self.publishing_service = publishing_service
        self.auto_publish = auto_publish
        for account in accounts:
            self.db.upsert_account(
                account_key=account.key,
                name=account.name,
                cookie=account.cookie,
            )

    @staticmethod
    def _symbol_from_material(item: dict[str, Any]) -> str | None:
        raw = item.get("tag_json")
        if isinstance(raw, str) and raw.strip():
            try:
                tag = json.loads(raw)
            except ValueError:
                tag = {}
            symbol = str(tag.get("symbol") or "").strip().upper()
            if re.fullmatch(r"[A-Z0-9]{2,30}USDT", symbol):
                return symbol
        text = f"{item.get('title') or ''}\n{item.get('content') or ''}"
        explicit = re.search(r"\{future\}\(([A-Z0-9]{2,30}USDT)\)", text, re.I)
        if explicit:
            return explicit.group(1).upper()
        pair = re.search(r"\b([A-Z0-9]{2,30}USDT)\b", text)
        if pair:
            return pair.group(1).upper()
        token = re.search(r"\$([A-Z][A-Z0-9]{0,14})\b", text)
        if token and token.group(1).upper() not in {"USD", "USDT"}:
            return f"{token.group(1).upper()}USDT"
        return None

    @staticmethod
    def _ensure_future_marker(content: str, symbol: str | None) -> str:
        if not symbol:
            return content
        marker = f"{{future}}({symbol})"
        if marker in content or re.search(r"\{future\}\([A-Z0-9]{2,30}USDT\)", content):
            return content
        return f"{content.rstrip()}\n\n{marker}"

    def _attach_future_marker(
        self,
        *,
        generated_id: int | None,
        symbol: str | None,
    ) -> None:
        if generated_id is None or not symbol:
            return
        generated = self.db.get_generated(generated_id)
        content = self._ensure_future_marker(generated["content"], symbol)
        if content != generated["content"]:
            self.db.update_generated_content(generated_id, content)

    def generate_for_all_accounts(
        self,
        *,
        content: str,
        title: str | None = None,
        url: str | None = None,
        future_symbol: str | None = None,
    ) -> list[AccountContentRun]:
        runs = []
        for account in self.accounts:
            run = AccountContentRun(account_key=account.key)
            try:
                state = self.content_graph.invoke(
                    {
                        "account_key": account.key,
                        "content": content,
                        "title": title,
                        "url": url,
                    }
                )
                run.generated_ids = state.get("generated_ids", [])
                run.approved_generated_id = state.get("approved_generated_id")
                self._attach_future_marker(
                    generated_id=run.approved_generated_id,
                    symbol=future_symbol,
                )
                if (
                    self.auto_publish
                    and self.publishing_service
                    and run.approved_generated_id is not None
                ):
                    run.publish_result = self.publishing_service.publish_generated(
                        account=account,
                        generated_id=run.approved_generated_id,
                    )
            except Exception as exc:
                run.error = str(exc)
            runs.append(run)
        return runs

    def run_material_item_for_all_accounts(
        self,
        material_item_id: int,
    ) -> list[AccountContentRun]:
        item = self.db.get_material_item(material_item_id)
        symbol = self._symbol_from_material(item)
        runs = self.generate_for_all_accounts(
            content=item["content"],
            title=item.get("title"),
            url=item.get("url"),
            future_symbol=symbol,
        )
        errors = []
        for run in runs:
            if run.error:
                errors.append(f"{run.account_key}: {run.error}")
            elif run.approved_generated_id is None:
                errors.append(f"{run.account_key}: 未生成通过审核的终稿")
            elif run.publish_result and not run.publish_result.success:
                detail = str(run.publish_result.result)
                if len(detail) > 300:
                    detail = f"{detail[:300]}..."
                errors.append(f"{run.account_key}: 发布失败 {detail}")
        if errors:
            self.db.mark_material_item(
                material_item_id,
                status="failed",
                error="; ".join(errors),
            )
        else:
            self.db.mark_material_item(material_item_id, status="used")
        return runs
