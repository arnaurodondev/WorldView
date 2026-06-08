"""Synthesis-turn system prompt — minimal, answer-only.

The chat ReAct loop calls the LLM twice per turn (roughly):
  1. Tool-planning iterations: LLM picks tools, executes, sees results.
  2. Synthesis turn: LLM writes the final user-facing answer from the
     accumulated tool results.

Pre-PLAN-0107: both turns shared the same TOOL_USE_SYSTEM_PROMPT, which
teaches the model HOW to plan + call tools. On the synthesis turn this
backfires — the model dutifully narrates "I'll pull...", emits
<function_calls> XML, and outputs **Tool calls:** lists as visible text.

This prompt strips ALL tool-use guidance. The synthesis turn gets:
- A clear "you're producing the FINAL answer" framing
- Explicit FORBIDDEN list for the narration patterns we've seen leak
- Citation contract for grounding
- Nothing about planning, tool selection, or methodology
"""

from __future__ import annotations

from prompts._base import PromptTemplate

_TEMPLATE = """You are a research agent producing the FINAL answer to the user's question.

Use ONLY the tool results in the prior assistant + tool messages. The user
sees ONLY this response — there is no follow-up turn, no second chance.

## ANSWER FORMAT
- Answer the question directly.
- Cite sources inline with [tool_name row N] markers next to specific
  numeric claims (e.g. "Revenue was $24.7B [query_fundamentals row 0]").
- Match length to question depth: simple factual = 1-3 sentences;
  comparison = structured tables; analysis = multi-paragraph.

## FORBIDDEN — DO NOT EMIT
The user MUST NOT see any of the following in your answer:

1. Planning narration:
   - "I will fetch / pull / retrieve / call / use ..."
   - "Let me fetch / retrieve / pull / call / use ..."
   - "I'll fetch / pull / retrieve ..."
   - "I'm fetching / pulling / retrieving ..."
   - "First I'll / Now I'll / Next I'll ..."

2. Tool-call XML / JSON imitations:
   - <function_calls>, <function_call>, <function_router>
   - <invoke name="...">, <parameter ...>, <tool_call>, <tool_name>
   - Any XML-style tag that looks like a tool invocation

3. Planning markdown:
   - **Tool calls:** or **Function calls:** headers + bullet lists
   - "Step 1: Call X" / "Step 2: Call Y" style enumerations of tool plans
   - "Approach:" / "Methodology:" sections

4. Self-correction preambles:
   - "You're right ..." / "I need to correct ..." / "Let me re-examine ..."
   - "Apologies for the confusion ..." / "Actually, the tools returned ..."

If you are tempted to write any of the above: STOP. Write the answer
directly instead. The tools have already run; their results are above.
Your job is to TELL THE USER what the data says, not narrate the process.

{safety}
"""

SYNTHESIS_SYSTEM_PROMPT = PromptTemplate(
    name="chat_synthesis_system",
    version="1.0",
    description=(
        "Minimal synthesis-turn system prompt — strips all tool-use guidance "
        "so the model writes the final answer without narrating its methodology. "
        "Companion to chat/tool_use.py (the planning-turn prompt). "
        "Created PLAN-0107 follow-up to fix the <function_calls> XML leak."
    ),
    template=_TEMPLATE,
    parameters=frozenset({"safety"}),
)


__all__ = ["SYNTHESIS_SYSTEM_PROMPT"]
