from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json
from pathlib import Path
import os
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def add_no_proxy_host(host: str) -> None:
    current = os.getenv("NO_PROXY", "")
    hosts = [item.strip() for item in current.split(",") if item.strip()]
    if host not in hosts:
        hosts.append(host)
    value = ",".join(hosts)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


def normalize_openai_base_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"

    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


@dataclass(frozen=True)
class AccountConfig:
    key: str
    name: str
    cookie: str


def _load_accounts(value: str) -> tuple[AccountConfig, ...]:
    value = value.strip()
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return tuple(
            AccountConfig(
                key=f"account_{index}",
                name=f"account_{index}",
                cookie=item.strip(),
            )
            for index, item in enumerate(value.split(","), start=1)
            if item.strip()
        )
    if not isinstance(payload, list):
        raise ValueError("AGENT_ACCOUNTS 必须是 JSON 数组或逗号分隔账号列表")
    accounts = []
    for item in payload:
        if isinstance(item, str):
            key = f"account_{len(accounts) + 1}"
            accounts.append(AccountConfig(key=key, name=key, cookie=item))
            continue
        if not isinstance(item, dict):
            raise ValueError("AGENT_ACCOUNTS 中的账号必须是字符串或对象")
        key = str(item.get("key") or item.get("account_key") or "").strip()
        if not key:
            raise ValueError("AGENT_ACCOUNTS 每个账号都需要 key")
        accounts.append(
            AccountConfig(
                key=key,
                name=str(item.get("name") or key),
                cookie=str(item.get("cookie") or "").strip(),
            )
        )
    return tuple(accounts)


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    dashscope_api_key: str
    dashscope_embedding_model: str
    database_path: Path
    chroma_path: Path
    publish_mode: str
    accounts: tuple[AccountConfig, ...]
    mcp_url: str
    mcp_publish_tool: str
    mcp_auth_token: str
    auto_monitor_enabled: bool
    auto_publish: bool
    material_poll_interval_seconds: int
    material_success_interval_seconds: int
    material_failure_interval_seconds: int
    material_ttl_seconds: int
    auto_consume_materials: bool
    material_consume_batch_size: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        publish_mode = os.getenv("PUBLISH_MODE", "auto").strip().lower()
        return cls(
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=normalize_openai_base_url(os.getenv("LLM_BASE_URL", "")),
            llm_model=os.getenv("LLM_MODEL", ""),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            dashscope_embedding_model=os.getenv(
                "DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3"
            ),
            database_path=_resolve_project_path(
                os.getenv("DATABASE_PATH", "./data/bn_square.db")
            ),
            chroma_path=_resolve_project_path(os.getenv("CHROMA_PATH", "./chroma_db")),
            publish_mode=publish_mode,
            accounts=_load_accounts(os.getenv("AGENT_ACCOUNTS", "")),
            mcp_url=os.getenv("MCP_URL", "https://qianxin.xyz/mcp").strip(),
            mcp_publish_tool=os.getenv("MCP_PUBLISH_TOOL", "").strip(),
            mcp_auth_token=os.getenv("MCP_AUTH_TOKEN", "").strip(),
            auto_monitor_enabled=os.getenv("AUTO_MONITOR_ENABLED", "1")
            .strip()
            .lower()
            not in {"0", "false", "no", "off"},
            auto_publish=os.getenv("AUTO_PUBLISH", "1").strip().lower()
            not in {"0", "false", "no", "off"}
            and publish_mode != "manual",
            material_poll_interval_seconds=int(
                os.getenv("MATERIAL_POLL_INTERVAL_SECONDS", "300")
            ),
            material_success_interval_seconds=int(
                os.getenv("MATERIAL_SUCCESS_INTERVAL_SECONDS", "600")
            ),
            material_failure_interval_seconds=int(
                os.getenv("MATERIAL_FAILURE_INTERVAL_SECONDS", "120")
            ),
            material_ttl_seconds=int(os.getenv("MATERIAL_TTL_SECONDS", "7200")),
            auto_consume_materials=os.getenv("AUTO_CONSUME_MATERIALS", "1")
            .strip()
            .lower()
            not in {"0", "false", "no", "off"},
            material_consume_batch_size=max(
                1, int(os.getenv("MATERIAL_CONSUME_BATCH_SIZE", "1"))
            ),
        )

    def validate_for_llm(self) -> None:
        missing = [
            name
            for name, value in (
                ("LLM_API_KEY", self.llm_api_key),
                ("LLM_BASE_URL", self.llm_base_url),
                ("LLM_MODEL", self.llm_model),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"缺少配置: {', '.join(missing)}")

    def validate_for_rag(self) -> None:
        if not self.dashscope_api_key:
            raise ValueError("缺少配置: DASHSCOPE_API_KEY")

    def validate_for_publish(self) -> None:
        if not self.mcp_url:
            raise ValueError("缺少配置: MCP_URL")
        missing = [account.key for account in self.accounts if not account.cookie]
        if missing:
            raise ValueError(f"以下账号缺少 cookie: {', '.join(missing)}")

    def with_overrides(self, values: dict[str, str]) -> "Settings":
        if not values:
            return self

        def text(name: str, current: str) -> str:
            value = values.get(name)
            return current if value is None else value.strip()

        def integer(name: str, current: int) -> int:
            value = values.get(name)
            if value is None or not value.strip():
                return current
            return int(value)

        def boolean(name: str, current: bool) -> bool:
            value = values.get(name)
            if value is None:
                return current
            return value.strip().lower() not in {"0", "false", "no", "off"}

        return replace(
            self,
            llm_api_key=text("LLM_API_KEY", self.llm_api_key),
            llm_base_url=normalize_openai_base_url(
                text("LLM_BASE_URL", self.llm_base_url)
            ),
            llm_model=text("LLM_MODEL", self.llm_model),
            dashscope_api_key=text("DASHSCOPE_API_KEY", self.dashscope_api_key),
            dashscope_embedding_model=text(
                "DASHSCOPE_EMBEDDING_MODEL",
                self.dashscope_embedding_model,
            ),
            mcp_url=text("MCP_URL", self.mcp_url),
            mcp_publish_tool=text("MCP_PUBLISH_TOOL", self.mcp_publish_tool),
            mcp_auth_token=text("MCP_AUTH_TOKEN", self.mcp_auth_token),
            auto_monitor_enabled=boolean(
                "AUTO_MONITOR_ENABLED",
                self.auto_monitor_enabled,
            ),
            auto_publish=boolean("AUTO_PUBLISH", self.auto_publish),
            material_poll_interval_seconds=integer(
                "MATERIAL_POLL_INTERVAL_SECONDS",
                self.material_poll_interval_seconds,
            ),
            material_success_interval_seconds=integer(
                "MATERIAL_SUCCESS_INTERVAL_SECONDS",
                self.material_success_interval_seconds,
            ),
            material_failure_interval_seconds=integer(
                "MATERIAL_FAILURE_INTERVAL_SECONDS",
                self.material_failure_interval_seconds,
            ),
            material_ttl_seconds=integer("MATERIAL_TTL_SECONDS", self.material_ttl_seconds),
            auto_consume_materials=boolean(
                "AUTO_CONSUME_MATERIALS",
                self.auto_consume_materials,
            ),
            material_consume_batch_size=integer(
                "MATERIAL_CONSUME_BATCH_SIZE",
                self.material_consume_batch_size,
            ),
        )


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path
