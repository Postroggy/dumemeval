"""MemoryBench 官方指标（28 子集异构）。

来源：benchmarks/continual/MemoryBench/ 各 src/dataset/*.py：
- Locomo-*：token F1（category5 adversarial：答对/答 no-information 得 1）
- DialSim-*：exact match，失败时 LLM judge fallback
- LexEval-*：ROUGE-L（中文按字符、拉丁按词的 CJK 感知分词）
- WritingPrompts：METEOR（exact+stem 对齐 + chunk penalty；无 WordNet 同义词档的近似）
- 生成型（HelloBench/IdeaBench/NFCats/WritingBench）：LLM judge score（注入 judge）

本实现：按子集路由到确定性指标；LLM 型子集用注入 judge（无 judge 时返回 0 并注明）。
"""

from __future__ import annotations

import itertools
import re
import string
from collections import Counter
from typing import Any, ClassVar

from ..core.base import MetricBundle, MetricCalculator, MetricInput, MetricKind
from .locomo import JudgeFn


def token_f1(prediction: str, gold: str) -> float:
    """LoCoMo 同款 token F1（normalize + Counter）。"""

    def norm(text: str) -> str:
        text = (text or "").lower()
        text = text.translate(str.maketrans("", "", string.punctuation))
        text = re.sub(r"\b(a|an|the|and)\b", " ", text)
        return " ".join(text.split())

    p = Counter(norm(prediction).split())
    g = Counter(norm(gold).split())
    common = p & g
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / sum(p.values()) if p else 0.0
    recall = num_same / sum(g.values()) if g else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def exact_match(prediction: str, gold: str) -> bool:
    return (prediction or "").strip().lower() == (gold or "").strip().lower()


def meteor_score(prediction: str, reference: str) -> float:
    """METEOR（exact + Porter stem 两档对齐；无 WordNet 同义词档的确定性近似）。

    score = Fmean × (1 − penalty)，Fmean = 10PR/(R+9P)（recall 加权 9:1），
    penalty = 0.5 × (chunks/matches)³，chunks = 两序列中均相邻的匹配段数。
    """
    from nltk.stem.porter import PorterStemmer

    p_tokens = _cjk_tokens((prediction or "").lower())
    r_tokens = _cjk_tokens((reference or "").lower())
    if not p_tokens or not r_tokens:
        return 0.0
    stemmer = PorterStemmer()

    # 贪心对齐：ref 每词在 pred 未用词中先找 exact，再找 stem 匹配
    used: set[int] = set()
    matches: list[tuple[int, int]] = []  # (pred_idx, ref_idx)
    for j, r_tok in enumerate(r_tokens):
        hit = None
        for i, p_tok in enumerate(p_tokens):
            if i not in used and p_tok == r_tok:
                hit = i
                break
        if hit is None:
            r_stem = stemmer.stem(r_tok)
            for i, p_tok in enumerate(p_tokens):
                if i not in used and stemmer.stem(p_tok) == r_stem:
                    hit = i
                    break
        if hit is not None:
            used.add(hit)
            matches.append((hit, j))

    m = len(matches)
    if m == 0:
        return 0.0
    precision = m / len(p_tokens)
    recall = m / len(r_tokens)
    f_mean = 10 * precision * recall / (recall + 9 * precision) if (recall + 9 * precision) else 0.0

    # chunks：按 pred 顺序遍历匹配对，相邻对在 pred 与 ref 上都 +1 连续才同段
    matches.sort()
    chunks = 1
    for (pi, ri), (pj, rj) in itertools.pairwise(matches):
        if not (pj == pi + 1 and rj == ri + 1):
            chunks += 1
    penalty = 0.5 * (chunks / m) ** 3
    return f_mean * (1 - penalty)


def _cjk_tokens(text: str) -> list[str]:
    """分词：拉丁文本按空白，CJK 文本按字符（连续拉丁段保词、连续 CJK 拆字）。

    LexEval 子集含中文；空白 split 对中文整句只会得到 1 个 token，ROUGE-L 失真。
    """
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
        elif "一" <= ch <= "鿿":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


def rouge_l_f1(prediction: str, reference: str) -> float:
    """ROUGE-L F1（token 级 LCS；中文按字符、拉丁按词）。"""
    p = _cjk_tokens((prediction or "").lower())
    r = _cjk_tokens((reference or "").lower())
    if not p or not r:
        return 0.0
    m, n = len(p), len(r)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if p[i - 1] == r[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs = dp[m][n]
    if lcs == 0:
        return 0.0
    precision = lcs / m
    recall = lcs / n
    return 2 * precision * recall / (precision + recall)


class MemoryBenchCalculator(MetricCalculator):
    """MemoryBench：按子集路由指标。"""

    name: ClassVar[str] = "memorybench"
    kind: ClassVar[MetricKind] = "benchmark"

    def __init__(self, judge: JudgeFn | None = None, llm_config: dict[str, Any] | None = None):
        self._judge = judge
        self._llm_config = llm_config

    def calculate(self, inp: MetricInput) -> MetricBundle:
        data = inp.task.data if inp.task is not None and isinstance(inp.task.data, dict) else {}
        samples = data.get("samples") or []
        by_dataset: dict[str, list[float]] = {}
        details: list[dict[str, Any]] = []
        n = 0
        for idx, sample in enumerate(samples):
            if not isinstance(sample, dict):
                continue
            n += 1
            query = str(sample.get("question") or "")
            dataset = str(sample.get("dataset") or "unknown")
            category = int(sample.get("category") or 0)
            golden = str(sample.get("golden_answer") or "")
            pred = next((item.output for item in inp.outputs if item.query == query), "")
            if not pred:
                outputs = list(inp.outputs)
                if idx < len(outputs):
                    pred = outputs[idx].output
            score = self._score_one(dataset, category, pred, golden, query)
            by_dataset.setdefault(dataset, []).append(score)
            details.append(
                {
                    "idx": idx,
                    "dataset": dataset,
                    "category": category,
                    "score": score,
                    "predicted": pred[:200],
                }
            )

        values: dict[str, float] = {
            "score": sum(v for vs in by_dataset.values() for v in vs) / n if n else 0.0
        }
        by_category: dict[str, dict[str, float]] = {}
        for ds, scores in by_dataset.items():
            by_category[ds] = {
                "score": sum(scores) / len(scores) if scores else 0.0,
                "count": float(len(scores)),
            }
            values[f"score_{ds}"] = by_category[ds]["score"]
        return MetricBundle(
            name=self.name, kind=self.kind, values=values, by_category=by_category, details=details
        )

    def _score_one(self, dataset: str, category: int, pred: str, golden: str, query: str) -> float:
        if not pred:
            return 0.0
        name = dataset.lower()
        if name.startswith("locomo"):
            # category5：拒答得 1
            if category == 5:
                lowered = pred.lower()
                return 1.0 if ("no information" in lowered or "not mentioned" in lowered) else 0.0
            return token_f1(pred, golden)
        if name.startswith("dialsim"):
            if exact_match(pred, golden):
                return 1.0
            # 官方 fallback：LLM judge
            if self._judge is not None:
                return 1.0 if self._judge(pred, golden, query) else 0.0
            return 0.0
        if name.startswith("lexeval"):
            return rouge_l_f1(pred, golden)
        if name.startswith("writingprompts"):
            # METEOR（exact+stem 对齐 + chunk penalty；同义词档未实现）
            return meteor_score(pred, golden)
        # 生成型（HelloBench/IdeaBench/NFCats/WritingBench）：LLM judge
        if self._judge is not None:
            return 1.0 if self._judge(pred, golden, query) else 0.0
        return 0.0
