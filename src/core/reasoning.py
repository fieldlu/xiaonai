"""Reasoning state machine - complexity classification + three-mode dispatch."""

import re
from dataclasses import dataclass
from typing import Optional


COMPLEX_KW = ["analyze", "compare", "explain", "why", "how", "difference",
              "分析", "比较", "解释", "为什么", "怎么", "如何", "区别",
              "帮我写", "总结", "翻译", "计算", "优化", "设计"]


@dataclass
class ReasoningPlan:
    mode: str  # SIMPLE | MODERATE | COMPLEX
    score: int
    thought_chain: Optional[str] = None
    needs_search: bool = False


def classify(message: str) -> ReasoningPlan:
    """Local complexity classification. Zero API cost."""
    score = 0
    if len(message) > 100:
        score += 1
    if message.count("?") + message.count("？") >= 3:
        score += 1
    if any(kw in message for kw in COMPLEX_KW):
        score += 1
    if "http://" in message or "https://" in message:
        score += 1
    if re.search(r"\[CQ:(image|file)", message):
        score += 2

    if score == 0:
        return ReasoningPlan(mode="SIMPLE", score=0)
    elif score <= 2:
        return ReasoningPlan(
            mode="MODERATE", score=score,
            thought_chain=_MODERATE_CHAIN
        )
    else:
        return ReasoningPlan(
            mode="COMPLEX", score=score,
            needs_search=True
        )


_MODERATE_CHAIN = """[Internal thought steps - do not output, guide reply only]
1. What is the user really asking?
2. What do I know from memory?
3. What don't I know?
4. Reply naturally in 2-3 sentences. Use plain language if explaining."""


async def execute_plan(
    plan: ReasoningPlan,
    llm_client,
    base_prompt: str,
    user_message: str,
    context: list,
    user_id: int,
    tools: list | None = None,
    tool_impl: dict | None = None,
) -> str:
    """Execute reasoning based on mode. Returns final reply text."""
    tools = tools or []
    tool_impl = tool_impl or {}

    if plan.mode == "SIMPLE":
        return await _single_call(llm_client, base_prompt, user_message, context, tools, tool_impl)

    elif plan.mode == "MODERATE":
        prompt = base_prompt + "\n\n" + _MODERATE_CHAIN
        return await _single_call(llm_client, prompt, user_message, context, tools, tool_impl)

    else:
        return await _per_cycle(llm_client, base_prompt, user_message, context, tools, tool_impl)


async def _single_call(client, system_prompt, user_msg, context, tools, tool_impl) -> str:
    messages = [{"role": "system", "content": system_prompt}]
    messages += context[-20:]
    messages.append({"role": "user", "content": user_msg})
    try:
        resp = await client.chat.completions.create(
            model="mimo-v2.5", messages=messages,
            tools=tools, temperature=0.8, max_tokens=600,
            timeout=15.0
        )
    except Exception:
        return "唔……小奈刚才走神了一下下，可以再说一次吗？(｡•́︿•̀｡)"

    choice = resp.choices[0]
    if choice.message.tool_calls:
        return await _handle_tools(client, messages, choice.message, tools, tool_impl, system_prompt)
    return choice.message.content or "诶？(°▽°)"


async def _per_cycle(client, system_prompt, user_msg, context, tools, tool_impl) -> str:
    # Plan phase
    plan_prompt = system_prompt + "\n\n[Plan mode] Analyze -> decompose -> identify info needs."
    plan_text = await _single_call(client, plan_prompt,
        "Plan for this question (output steps):\n" + user_msg,
        context, tools, tool_impl)

    # Execute phase
    exec_prompt = system_prompt + "\n\n[Execute mode] Follow the plan, call tools as needed."
    exec_text = await _single_call(client, exec_prompt,
        "Plan: " + plan_text + "\nQuestion: " + user_msg + "\nExecute the plan.",
        context, tools, tool_impl)

    # Reflect phase
    refl_prompt = system_prompt + "\n\n[Reflect mode] Verify sufficiency and coherence. Generate final reply."
    final = await _single_call(client, refl_prompt,
        "Question: " + user_msg + "\nCollected info: " + exec_text + "\nVerify and reply.",
        context, tools, tool_impl)
    return final


async def _handle_tools(client, messages, assistant_msg, tools, tool_impl, system_prompt) -> str:
    """Recursive tool call handling (max 5 iterations)."""
    import json as _json
    for _ in range(5):
        messages.append(assistant_msg)
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            try:
                args = _json.loads(tc.function.arguments)
            except Exception:
                args = {}
            if fn_name in tool_impl:
                try:
                    result = await tool_impl[fn_name](**args)
                except Exception as e:
                    result = "Tool error: " + str(e)
            else:
                result = "Unknown tool: " + fn_name
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(result)
            })
        resp = await client.chat.completions.create(
            model="mimo-v2.5", messages=messages,
            tools=tools, temperature=0.8, max_tokens=600,
            timeout=15.0
        )
        choice = resp.choices[0]
        if choice.message.content and not choice.message.tool_calls:
            return choice.message.content
        if choice.message.tool_calls:
            assistant_msg = choice.message
            continue
        return "唔……小奈想了想，这个问题有点复杂呢……(´・ω・`)"
    return "诶……小奈尽力了但还是不太确定呢 (´;ω;`)"
