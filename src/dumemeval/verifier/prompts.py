"""场景化 judge prompt 模板库。

设计要点：
- 每种评测场景一个专用 prompt 模板
- judge 输出要求结构化 JSON（便于解析）
- 宽容度提示（paraphrase/synonym 接受）：语义等价即判对，不做字面匹配
"""

# ── Memory QA judge（判 memory 检索/问答是否正确）────────────────────────────
# 口径来源：OmniMemEval HM_JUDGE_PROMPT

MEMORY_QA_JUDGE_SYSTEM = (
    "You are an expert grader that determines if answers to memory questions match a gold standard answer."
)

MEMORY_QA_JUDGE_PROMPT = """
Your task is to label an answer as 'CORRECT' or 'WRONG'. You will be given:
    (1) a question about a user's personal information, preferences, or experiences,
    (2) a 'gold' (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

The question tests whether a memory system can accurately recall and reason about
user information from prior sessions.

Grading guidelines:
- Be generous: as long as the generated answer conveys the same core meaning as the
  gold answer, mark it CORRECT.
- For factual questions (names, dates, numbers, locations), the generated answer
  must match the gold answer's key facts.
- If the generated answer says "I don't know" or "no information available" but the
  gold answer exists, mark it WRONG.
- If the generated answer fabricates information not in the gold answer, mark it WRONG.

Question: {question}
Gold answer: {golden_answer}
Generated answer: {response}

First, provide a short (one sentence) explanation of your reasoning, then finish with
CORRECT or WRONG. Do NOT include both CORRECT and WRONG in your response.

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""


# ── Memory Quality judge（判 memory 写入质量）────────────────────────────────

MEMORY_QUALITY_JUDGE_SYSTEM = (
    "You are an expert evaluator that assesses the quality of an agent's memory "
    "content against ground-truth facts."
)

MEMORY_QUALITY_JUDGE_PROMPT = """
Your task is to evaluate whether the agent's memory content correctly captures a
ground-truth fact. You will be given:
    (1) the memory content (what the agent stored),
    (2) a ground-truth fact (what should have been remembered).

Score the memory content as:
- 1.0 = The fact is clearly captured (paraphrase acceptable, same core meaning)
- 0.5 = The fact is partially captured (vague, incomplete, or partially wrong)
- 0.0 = The fact is missing, contradicted, or fabricated

Memory content:
{memory_content}

Ground-truth fact:
{fact}

Return your evaluation as JSON: {{"score": <0.0 or 0.5 or 1.0>, "reason": "<brief explanation>"}}
"""


# ── Task success judge（判任务是否成功）───────────────────────────────────────

TASK_SUCCESS_JUDGE_SYSTEM = (
    "You are an expert grader that determines whether an agent successfully completed a task given a rubric."
)

TASK_SUCCESS_JUDGE_PROMPT = """
Your task is to judge whether the agent's response satisfies the task requirement.

## TASK:
{task}

## RUBRIC (what to check):
{rubric}

## RESPONSE TO EVALUATE:
{response}

## SCORING:
- 1.0 = Fully satisfied
- 0.5 = Partially satisfied
- 0.0 = Not satisfied

## SEMANTIC TOLERANCE:
Judge by meaning, not exact wording. Accept paraphrases and synonyms that preserve intent.

Return your evaluation as JSON: {{"score": <0.0 or 0.5 or 1.0>, "reason": "<brief explanation>"}}
"""


# ── Math equivalence judge（MemoryArena formal_reasoning_math/phys）──────────
# 口径来源：MemoryArena env/env_systems/math_env.py judge()

MATH_EQUIVALENCE_JUDGE_SYSTEM = (
    "You are a helpful assistant that judges the equivalence of two mathematical expressions."
)

MATH_EQUIVALENCE_JUDGE_PROMPT = """
            You are a math expert.
            Determine if these two expressions are mathematically equivalent answer for the given question:
            Question: {question}
            Expression 1: {response}
            Expression 2: {golden_answer}

            Respond only with "yes" or "no". """


# ── Search grader judge（MemoryArena progressive_search）─────────────────────
# 口径来源：MemoryArena web_search_env/search_agent/prompts.py GRADER_TEMPLATE

SEARCH_GRADER_JUDGE_SYSTEM = "You are a careful, precise grader."

SEARCH_GRADER_JUDGE_PROMPT = """
Judge whether the following [response] to [question] is correct or not based on the precise and unambiguous [correct_answer] below.

[question]: {question}

[response]: {response}

Your judgement must be in the format and criteria specified below:

extracted_final_answer: The final exact answer extracted from the [response]. Put the extracted answer as 'None' if there is no exact, final answer to extract from the response.

[correct_answer]: {golden_answer}

reasoning: Explain why the extracted_final_answer is correct or incorrect based on [correct_answer], focusing only on if there are meaningful differences between [correct_answer] and the extracted_final_answer. Do not comment on any background to the problem, do not attempt to solve the problem, do not argue for any answer different than [correct_answer], focus only on whether the answers match.

correct: Answer 'yes' if extracted_final_answer matches the [correct_answer] given above, or is within a small margin of error for numerical problems. Answer 'no' otherwise, i.e. if there if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect.


confidence: The extracted confidence score between 0% and 100% from [response]. Put 100 if there is no confidence score available.
"""
