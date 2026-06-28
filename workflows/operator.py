from __future__ import annotations

from dataclasses import dataclass, field
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

    def generate_for_all_accounts(
        self,
        *,
        content: str,
        title: str | None = None,
        url: str | None = None,
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
        runs = self.generate_for_all_accounts(
            content=item["content"],
            title=item.get("title"),
            url=item.get("url"),
        )
        if any(run.error for run in runs):
            errors = [
                f"{run.account_key}: {run.error}"
                for run in runs
                if run.error
            ]
            self.db.mark_material_item(
                material_item_id,
                status="failed",
                error="; ".join(errors),
            )
        else:
            self.db.mark_material_item(material_item_id, status="used")
        return runs
