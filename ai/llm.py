from __future__ import annotations

import json
import re
from typing import TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from ..core.config import Settings


T = TypeVar("T", bound=BaseModel)


class StructuredLLM:
    def __init__(self, settings: Settings):
        settings.validate_for_llm()
        self.model = settings.llm_model
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=45.0,
            max_retries=1,
            http_client=httpx.Client(timeout=45.0, trust_env=False),
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        first_object = text.find("{")
        first_array = text.find("[")
        starts = [position for position in (first_object, first_array) if position >= 0]
        if not starts:
            return text
        start = min(starts)
        closing = "}" if text[start] == "{" else "]"
        end = text.rfind(closing)
        return text[start : end + 1] if end >= start else text[start:]

    def invoke(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        retries: int = 2,
    ) -> T:
        schema = json.dumps(
            response_model.model_json_schema(), ensure_ascii=False, indent=2
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\n"
                    "只输出一个合法 JSON，不要输出 Markdown 或解释。"
                    f"\nJSON 必须符合以下 schema：\n{schema}"
                ),
            },
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None
        for _ in range(retries + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            try:
                return response_model.model_validate_json(self._extract_json(text))
            except (ValidationError, ValueError) as exc:
                last_error = exc
                messages.extend(
                    [
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": (
                                "返回内容未通过格式校验。请修正并只输出合法 JSON。"
                                f"\n错误：{exc}"
                            ),
                        },
                    ]
                )
        raise RuntimeError(f"模型结构化输出失败: {last_error}")
