from __future__ import annotations

import json
from typing import Iterable

from .llm import StructuredLLM
from ..models.schemas import (
    Candidate,
    CandidateSet,
    ContentReview,
    PostAnalysis,
    ProfileBatchSummary,
    StyleProfile,
)


def as_json(value: object) -> str:
    if isinstance(value, list):
        payload = [
            item.model_dump() if hasattr(item, "model_dump") else item for item in value
        ]
    elif hasattr(value, "model_dump"):
        payload = value.model_dump()
    else:
        payload = value
    return json.dumps(payload, ensure_ascii=False, indent=2)


class AnalysisAgent:
    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def analyze(self, content: str) -> PostAnalysis:
        return self.llm.invoke(
            system_prompt=(
                "你是加密市场短帖分析 Agent。只提取原文明示的信息，"
                "不得补充原文没有的理由、事实或判断。分析结果使用中文。"
            ),
            user_prompt=f"分析以下目标作者历史文章：\n\n{content}",
            response_model=PostAnalysis,
        )


class StyleProfileAgent:
    BATCH_SIZE = 20

    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def _summarize_batch(self, analyses: list[dict]) -> ProfileBatchSummary:
        return self.llm.invoke(
            system_prompt=(
                "你是写作风格归纳 Agent。根据一批文章分析结果总结反复出现、"
                "可观察的写作模式。不要推断真实身份、人格或未出现的观点。"
            ),
            user_prompt=f"归纳这批历史文章分析：\n{as_json(analyses)}",
            response_model=ProfileBatchSummary,
        )

    def build(self, analyses: list[dict]) -> StyleProfile:
        if not analyses:
            raise ValueError("没有成功分析的历史文章，无法生成写作风格档案")
        batches = [
            analyses[index : index + self.BATCH_SIZE]
            for index in range(0, len(analyses), self.BATCH_SIZE)
        ]
        summaries = [self._summarize_batch(batch) for batch in batches]
        return self.llm.invoke(
            system_prompt=(
                "你是写作风格档案 Agent。合并所有分批摘要，生成稳定、具体、"
                "可用于改写的风格档案。只描述文章中可观察到的模式。"
            ),
            user_prompt=(
                f"历史文章总数：{len(analyses)}\n"
                f"分批摘要：\n{as_json(summaries)}"
            ),
            response_model=StyleProfile,
        )


class WriterAgent:
    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def generate(
        self,
        *,
        material: str,
        profile: StyleProfile,
        similar_analyses: list[dict],
    ) -> list[Candidate]:
        result = self.llm.invoke(
            system_prompt=(
                "你是 BN 广场内容 Writer Agent。把外部素材改写成目标作者风格。"
                "必须保留素材事实，不得添加素材没有的新事实、数据、消息或来源。"
                "允许加入预测和观点，但必须用可能、预计、我认为、关注等措辞"
                "明确表达不确定性，且理由只能来自素材事实和历史中反复出现的"
                "判断逻辑。不得复制素材或历史文章的原句、句式和段落。"
                "一次生成三篇候选，三篇的切入角度、开头和结构应明显不同。"
                "不设置固定字数。"
            ),
            user_prompt=(
                f"外部素材：\n{material}\n\n"
                f"写作风格档案：\n{as_json(profile)}\n\n"
                "相似历史文章的结构化分析（只学习风格和判断逻辑）：\n"
                f"{as_json(similar_analyses)}"
            ),
            response_model=CandidateSet,
        )
        by_index = {candidate.candidate_index: candidate for candidate in result.candidates}
        if set(by_index) != {1, 2, 3}:
            raise ValueError("Writer 必须生成 candidate_index 为 1、2、3 的候选稿")
        return [by_index[index] for index in (1, 2, 3)]

    def rewrite(
        self,
        *,
        material: str,
        profile: StyleProfile,
        candidate: Candidate,
        review: ContentReview,
    ) -> Candidate:
        return self.llm.invoke(
            system_prompt=(
                "你是 BN 广场内容 Writer Agent。根据审核反馈重写候选稿。"
                "不得添加素材没有的新事实。允许明确标注为不确定的预测。"
                "必须解决全部审核问题，并保持目标作者的写作风格。"
            ),
            user_prompt=(
                f"外部素材：\n{material}\n\n"
                f"写作风格档案：\n{as_json(profile)}\n\n"
                f"待重写候选：\n{as_json(candidate)}\n\n"
                f"审核反馈：\n{as_json(review)}\n\n"
                f"保持 candidate_index={candidate.candidate_index}。"
            ),
            response_model=Candidate,
        )


class ContentReviewAgent:
    def __init__(self, llm: StructuredLLM):
        self.llm = llm

    def review(
        self,
        *,
        material: str,
        profile: StyleProfile,
        similar_analyses: list[dict],
        candidate: Candidate,
    ) -> ContentReview:
        review = self.llm.invoke(
            system_prompt=(
                "你是独立内容审核 Agent，只审核，不修改文章。逐项检查："
                "1. 是否捏造素材没有的新事实；2. 是否把预测写成事实；"
                "3. 是否偏离素材；4. 是否复制素材或历史表达；"
                "5. 是否符合写作风格档案。评分必须严格。事实忠实度只有"
                "完全没有新增或扭曲事实时才能给 10 分。"
            ),
            user_prompt=(
                f"外部素材：\n{material}\n\n"
                f"风格档案：\n{as_json(profile)}\n\n"
                f"相似历史分析：\n{as_json(similar_analyses)}\n\n"
                f"候选稿：\n{as_json(candidate)}\n\n"
                "合格标准：事实忠实度=10；风格匹配度、原创度、表达质量均>=7。"
                "不合格时给出具体 issues 和可执行 rewrite_instructions。"
            ),
            response_model=ContentReview,
        )
        review.passed = review.meets_threshold()
        return review
