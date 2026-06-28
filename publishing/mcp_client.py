from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from typing import Any

import httpx


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


class RemoteMCPClient:
    def __init__(
        self,
        url: str,
        *,
        auth_token: str = "",
        timeout: float = 60.0,
    ):
        self.url = url
        self.auth_token = auth_token
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            return response.json()
        data_lines = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if not data_lines:
            raise MCPError("MCP SSE 响应没有 data 内容")
        return json.loads(data_lines[-1])

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params or {},
        }
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.post(self.url, headers=self._headers(), json=payload)
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        message = self._parse_response(response)
        if "error" in message:
            raise MCPError(f"MCP {method} 失败: {message['error']}")
        return message.get("result")

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "bn-square-agent",
                    "version": "1.0.0",
                },
            },
        )
        self.notify("notifications/initialized")
        return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.post(self.url, headers=self._headers(), json=payload)
        response.raise_for_status()

    def list_tools(self) -> list[MCPTool]:
        result = self.request("tools/list")
        return [
            MCPTool(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema"),
            )
            for tool in result.get("tools", [])
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        return result if isinstance(result, dict) else {"result": result}
