"""Verifier 判分体系（Rule + Factory）。

- base.py: Verdict / BaseVerifier
- llm.py: LLMJudgeVerifier
- rule.py: RuleVerifier（本文件）
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from .base import BaseVerifier, Verdict
from .llm import LLMJudgeVerifier


class RuleVerifier(BaseVerifier):
    """规则判分器（无 LLM，快且确定）。

    config:
        mode: substring（子串匹配） / regex（正则） / exact（精确匹配）
        case_sensitive: 默认 False
    """

    name = "rule"

    def verify(self, response: str, ground_truth: str, **ctx: Any) -> Verdict:
        mode = self.config.get("mode", "substring")
        case = self.config.get("case_sensitive", False)
        r, gt = response, ground_truth
        if not case:
            r, gt = r.lower(), gt.lower()

        if mode == "exact":
            ok = r.strip() == gt.strip()
        elif mode == "regex":
            try:
                ok = re.search(gt, r) is not None
            except re.error as e:
                return Verdict(label="ERROR", score=0.0, reason=f"bad regex: {e}")
        else:  # substring
            ok = gt in r

        return Verdict(
            label="CORRECT" if ok else "WRONG",
            score=1.0 if ok else 0.0,
            reason="rule match" if ok else "no match",
        )


# ── Factory ─────────────────────────────────────────────────────────────────


class VerifierFactory:
    """按 config 创建 verifier（可注册自定义类型）。"""

    _VERIFIERS: ClassVar[dict[str, type[BaseVerifier]]] = {
        "llm_judge": LLMJudgeVerifier,
        "rule": RuleVerifier,
    }

    @classmethod
    def create(cls, config: dict[str, Any] | None) -> BaseVerifier:
        config = config or {}
        vtype = config.get("type", "rule")
        verifier_cls = cls._VERIFIERS.get(vtype)
        if verifier_cls is None:
            raise ValueError(f"Unknown verifier type: {vtype!r}. Supported: {list(cls._VERIFIERS)}")
        return verifier_cls(config)

    @classmethod
    def register(cls, vtype: str, verifier_cls: type[BaseVerifier]) -> None:
        """注册自定义 verifier（扩展点）。"""
        cls._VERIFIERS[vtype] = verifier_cls
