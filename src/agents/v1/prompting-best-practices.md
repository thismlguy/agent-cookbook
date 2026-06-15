# Prompting best practices applied to v1

Reference notes for v1's system prompt. The point of this document: capture which prompting principles we drew from where, so future iterations can build on them deliberately rather than ad hoc.

v1 is structurally identical to v0 — same ReAct loop, same tools, same model (Kimi K2.6 via OpenRouter). The differences are entirely in how the system prompt is structured.

---

## References consulted

| # | Source | Why we used it |
|---|---|---|
| 1 | [Prompt engineering overview](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview) — Anthropic | Entry point. Recommends defining success criteria + evals before prompt tuning. We have both, so we're in scope to iterate. |
| 2 | [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices) — Anthropic | The technique catalogue: clarity, examples, XML structuring, role prompting, chain-of-thought, prompt chaining. |
| 3 | [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) — Anthropic | Tools matter as much as prompts. Namespacing, meaningful context, token efficiency, error response design. |
| 4 | [Building effective agents](https://www.anthropic.com/research/building-effective-agents) — Anthropic | Distinguishes *workflows* (predefined steps) from *agents* (dynamic decisions). Our agent is the latter. |
| 5 | [Prompt engineering for AI agents](https://www.prompthub.us/blog/prompt-engineering-for-ai-agents) — PromptHub | Case studies of production agent system prompts (Cline, Bolt). Patterns: structured tool use, plan-then-act, environmental context, safety checks before mutating actions. |

---

## Key practices applied

### 1. XML-tagged sections rather than a verbatim block
*Source: best-practices catalogue (#2).* XML tags are well-established as a structuring convention across model families (not just Claude — Kimi, GPT, and Gemini all handle them well). v0 fed the policy in as raw markdown; v1 wraps the policy's existing sections in semantic tags (`<role>`, `<general_rules>`, `<booking>`, `<modification>`, etc.). The model can now attend to specific sections by name, and we can refer to them precisely from inside other prompt machinery (e.g., a critic that says "check the response against `<refunds_and_compensation>`").

### 2. No content duplication
*Source: best-practices catalogue (#2) — "be clear and direct."* The first version of v1 had a framing layer that restated the policy's role, scope, confirm-before-write rule, transfer rules, and one-action-per-turn rule — all of which were already in the policy. That's noise. v1 now restructures the policy itself with XML, so the role, scope, and rules are stated once. The framing in `prompt.py` adds only what the policy doesn't cover.

### 3. Hierarchical structure mirrors operations
*Source: PromptHub agent patterns (#5).* Cline's prompt uses nested tags to delineate tool docs, modes, and protocols. We do the same with the policy: `<modification>` contains `<change_flights>`, `<change_cabin>`, `<change_baggage_and_insurance>`, `<change_passengers>`, `<payment_for_modifications>`. Each rule is in the smallest tag that applies — easier for the model to retrieve.

### 4. Lean framing
*Source: multiple, including [a customer support eval cited by buildmvpfast](https://www.buildmvpfast.com/blog/system-prompt-design-best-practices-llm-instructions-engineering-2026).* Base prompts in the 200-800 token range typically outperform 3000+ token prompts on multi-step reasoning. v1's policy is the bulk; the only thing prompt.py adds on top is a ~60-token `<response_style>` tag — the one piece of guidance the policy genuinely doesn't cover.

### 5. Tell the model how to talk to the user
*Source: best-practices catalogue (#2).* The policy says *what* the agent does, not *how* it should communicate. The `<response_style>` tag fills that gap: state outcomes plainly, be concise, acknowledge but don't over-apologize. Three short rules.

### 6. Positive imperatives
*Source: best-practices catalogue (#2).* "Tell the model what to do, not what not to do." Where possible, the response_style rules are framed positively ("state outcomes plainly", "be concise"). The "do not" forms remain only where the action is the failure mode itself (e.g., "do not quote eligibility rules").

---

## What we deliberately did not include

- **Few-shot examples (3–5 worked transcripts).** Would improve specific behaviors but bloats the prompt and risks the model imitating exemplars too literally. Defer until v1 eval shows specific gaps examples would close.
- **Chain-of-thought instructions.** The model can decide when to reason. No need to mandate `<thinking>` blocks in a ReAct loop.
- **Failure-specific guardrails.** v0's eval showed specific failure modes (over-transfer, false promises, etc.). v1 deliberately doesn't encode those — the point is to see what cleaner *structure* does on its own. v2+ can add targeted guardrails once we compare v1 eval data to v0.

---

## How to iterate from here

After running v1 against the 50-task eval:

1. **Diff against v0.** Which failure modes did better structure alone fix?
2. **Categorize remaining failures** by what would fix them: another prompt change, a tool change, or a process change.
3. **Prompt-fixable** → either tighten a tag's content, or introduce a few-shot example for the specific behavior. Update this doc with rationale.
4. **Tool-fixable** → that's v2 (tighter schemas, validator tool, search wrapper).
5. **Process-fixable** → that's v3 (critic, planner-executor, multi-agent).

The discipline this doc enforces: every prompt change should cite a referenced practice or an observed eval gap, not an aesthetic preference.
