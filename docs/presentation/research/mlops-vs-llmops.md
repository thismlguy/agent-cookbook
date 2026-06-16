# Research: MLOps → LLMOps → AgentOps

Source material for **Section 1** of the presentation flow
([`../00-flow.md`](../00-flow.md)). Annotated resources, claim-level citations,
the comparison table, and reusable framings. Skeptic notes flag hype vs
substance.

---

## 1. Resources (annotated)

### Primary / authoritative

| Source | URL | What it contributes |
|---|---|---|
| **AWS — Operationalizing Generative AI: How It Differs from MLOps** | https://aws.amazon.com/blogs/machine-learning/operationalizing-generative-ai-how-it-differs-from-mlops/ | Cleanest axis-by-axis MLOps-vs-GenAIOps contrast from a major vendor: artifact shipped, dev loop, evaluation (HIL + LLM-as-judge), prompt catalog "like a Git repo," new roles. |
| **AWS — FMOps/LLMOps: Operationalize generative AI and differences with MLOps** | https://aws.amazon.com/blogs/machine-learning/fmops-llmops-operationalize-generative-ai-and-differences-with-mlops/ | The **FMOps ⊃ LLMOps** framing and new personas (prompt engineer, prompt tester, data labeler). Good for the team/skills slide. |
| **Anthropic — Effective context engineering for AI agents** | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | The model-is-frozen thesis. Context engineering as successor to prompt engineering; new iteration unit = "what configuration of context is most likely to generate the desired behavior." |
| **Anthropic — Building Effective Agents** | https://www.anthropic.com/research/building-effective-agents | Agent-vs-workflow distinction; tool design (ACI / poka-yoke); guardrails; human-in-the-loop; "build the *right* system, not the most sophisticated." |
| **a16z — Emerging Architectures for LLM Applications** | https://a16z.com/emerging-architectures-for-llm-applications/ | The reference LLM-app-stack diagram; "in-context learning reduces an AI problem to a data engineering problem." **Caveat: 2023 — its "agents don't work yet" claim is stale; cite for the stack only.** |
| **Thinking Machines Lab — Defeating Nondeterminism in LLM Inference** | https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/ | Why LLM inference is non-deterministic *even at temperature 0* (batch-invariance / floating-point reduction order, not just sampling). Best technical source for the reproducibility axis. |

### Strong secondary / practitioner

| Source | URL | What it contributes |
|---|---|---|
| **Google Cloud — Master Generative AI Evaluation** | https://cloud.google.com/blog/topics/developers-practitioners/master-generative-ai-evaluation-from-single-prompts-to-complex-agents | Moving from "vibes-based" to metrics-driven eval, and from single-output to multi-step **trajectory** evaluation. |
| **Microsoft / Azure Databricks — LLMOps workflows** | https://learn.microsoft.com/en-us/azure/databricks/machine-learning/mlops/llmops | Reference architecture; prompt/chain versioning and eval-in-CI. |
| **Databricks — The Big Book of MLOps (GenAI edition)** | https://www.databricks.com/resources/ebook/the-big-book-of-mlops | Positions LLMOps as a *superset* of MLOps with added RAG/prompt layers. Marketing-flavored; architectures usable. |
| **Hugging Face — Evaluation Guidebook** | https://huggingface.co/spaces/OpenEvals/evaluation-guidebook | Automated vs human vs LLM-as-judge eval and the pitfalls of each. Least-hype eval resource here. |
| **Langfuse** | https://langfuse.com/ | Open-source LLM trace/span observability; de-facto example of "tracing reasoning + tool calls." (This repo's observability layer.) |
| **The Pragmatic Engineer — A pragmatic guide to LLM evals** | https://newsletter.pragmaticengineer.com/p/evals | "If you ship LLM features without evals, you're guessing." Good tone for the talk. |
| **OWASP — AI Agent Security Cheat Sheet / Top 10 for LLMs** | https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html | Prompt injection, **excessive agency**, tool misuse; least-privilege tooling, human approval for high-risk actions, action screening. |
| **arXiv — You've Changed: Detecting Modification of Black-Box LLMs** | https://arxiv.org/pdf/2504.12335 | Evidence API models change silently; >60% of evaluated APIs showed substantial performance change over time. Backs "model drift behind an API." |
| **arXiv — Catching One in Five: LLM-as-Judge Blind Spots in Multi-Turn Agents** | https://arxiv.org/html/2606.10315 | A production LLM-judge caught ~22% of human-confirmed systematic defects and flagged 0/100 rounds where humans found 23 — catches turn-local issues, misses cross-turn state. Best "be skeptical of LLM-as-judge" citation. |

### Hype-vs-substance flags
- **"AgentOps ultimate guide" Medium/vendor posts** (XenonStack, ZBrain, etc.) are mostly definitional marketing. The *concept* (trace the full execution graph, model per-session loop cost, enforce runtime policy) is real and consistent; cite the primary sources for substance.
- **a16z is 2023** — excellent for the stack diagram, stale on agents.
- **"LLMOps = MLOps + a few layers" vendor posts** converge on a genuine insight (LLMOps *extends* MLOps) but inflate it into product pitches. Insight sound; urgency is sales.

---

## 2. Conceptual contrasts (axes, with substance)

**A. What is the "model" you ship.** ML: you *train weights*; the artifact is a versioned model file; the model *is* the product. Agentic LLM: you ship **prompt + tools + context + policy** around a **frozen foundation model you don't own** (a16z: in-context learning over an API model; Anthropic: "managing what information reaches it"). Strong agreement across sources.

**B. Development loop.** ML: linear, **data-centric** (collect/label → train → validate → test). Agent: iterative, **behavior/context-centric** (prompt/tools → eval → traces → revise context). Data still matters (RAG corpora, few-shot, eval sets) but you change *context configuration*, not weights.

**C. Evaluation.** ML: deterministic single-number metrics on a fixed held-out set (accuracy/precision/recall/F1/AUC); re-runnable, objective. Agent: **hybrid + subjective** — human-in-the-loop + **LLM-as-judge** + similarity metrics over **multi-turn trajectories**. *Skeptic's note (load-bearing):* LLM-as-judge is not a drop-in test set — "Catching One in Five" found ~22% catch rate on systematic defects, 0/100 on cross-turn state. Noisy instrument requiring human calibration.

**D. Determinism & reproducibility.** ML: effectively deterministic; fix model + input → same output. Agent: **stochastic by default** *and non-deterministic even at temp 0* (Thinking Machines: batch-invariance / FP reduction order). Plus **model drift behind an API** ("You've Changed": >60% of APIs changed substantially). Regression testing must be **statistical**; you can't pin a hosted model like a `.pkl`.

**E. Failure modes.** ML: overfitting, data/concept drift, train-serve skew — *statistical* degradation. Agent: **hallucination, prompt injection, tool misuse / excessive agency** (OWASP), and **cascading errors across multi-step trajectories**. Adversarial and emergent, not just statistical.

**F. Unit of iteration.** ML: features, hyperparameters, architecture, training data. Agent: **prompt → tools → policy → context** ("context engineering"). The "hyperparameters" are the prompt template, tool schemas, retrieval strategy, policy text.

**G. Pipeline non-determinism (control flow).** ML: the pipeline is a **DAG you author** — fixed, inspectable. Agent: it **decides its own control flow at runtime**. Anthropic: workflows = "predefined code paths"; agents = "dynamically direct their own processes and tool usage." Biggest single shift.

**H. Observability.** ML: aggregate **metrics dashboards**. Agent: **full trace/span trees** of reasoning + every tool call, with tokens/latency/cost per span (Langfuse). You debug a *call tree*, not a metric. Drift monitoring broadens to refusal patterns, retries, behavioral drift.

**I. Cost & latency.** ML: cost front-loaded (training); inference cheap and flat. Agent: **per-call token cost**, **amplified multiplicatively by multi-step loops**. Mitigations are new ops surface: prompt caching, model routing, step budgets. Cost is a *runtime control problem*.

**J. Data & versioning.** ML: version **dataset + weights** (DVC, registry). Agent: version **prompts, context templates, tool schemas, eval sets**. AWS: a centralized **"prompt catalog … like a Git repository."** Tool schema = versioned contract ("the contract between the agent and the action space").

**K. Safety / guardrails.** ML: input validation at the boundary. Agent: **defense-in-depth around an untrusted reasoner** — confirmation gates / human approval for high-risk actions, **least-privilege tooling**, **action screening** against original intent (OWASP). Practical pattern: **take destructive writes off the LLM's tool surface** — model *proposes*, a deterministic/gated path *commits*. (Exactly this repo's v2 pending-action store — `src/agents/v2/architecture.md`.)

**L. Team / skills shift.** ML: feature engineering, model training, statistical validation. Agent: **context engineering, eval design, system design.** FMOps adds personas (prompt engineer, prompt tester, GenAI developer, data labeler).

---

## 3. Comparison table (slide-ready)

| Axis | Traditional ML system | Agentic LLM system |
|---|---|---|
| **What you ship** | Trained weights / model artifact | Prompt + tools + context + policy around a frozen foundation model |
| **You control** | The model itself | Everything *around* the model (model is a fixed API) |
| **Dev loop** | Collect → label → train → validate → test (data-centric) | Prompt → eval → trace → revise context (behavior/context-centric) |
| **Iteration unit** | Features, hyperparameters, architecture | Prompts, tool schemas, retrieval, policy ("context engineering") |
| **Evaluation** | Accuracy / F1 / AUC on held-out set; objective, re-runnable | LLM-as-judge + human review over multi-turn trajectories; subjective, noisy |
| **Determinism** | Deterministic inference; reproducible | Stochastic even at temp 0; reproducibility is statistical |
| **Model stability** | You pin the weights | Provider can silently update the API model (drift) |
| **Control flow** | A DAG you author and fully control | The agent decides its own steps at runtime |
| **Failure modes** | Overfitting, data/concept drift, skew | Hallucination, prompt injection, tool misuse, cascading multi-step errors |
| **Observability** | Aggregate metrics dashboards | Full trace/span trees of reasoning + tool calls (e.g. Langfuse) |
| **Cost / latency** | One-time training cost; cheap, flat inference | Per-call token cost, amplified by multi-step loops; caching/routing/budgets |
| **Versioning** | Dataset + weights | Prompt catalog + context + tool schemas + eval sets |
| **Safety / guardrails** | Input validation at the boundary | Confirmation gates, least-privilege tools, action screening; writes off the LLM surface |
| **Team skills** | Feature engineering, model training | Context engineering, eval design, system design |

---

## 4. Framings & mental models

Verified / directly grounded:
- *"The evolution isn't about changing [the model] itself, but … managing what information reaches it."* — Anthropic, context engineering.
- Workflows vs agents: *"orchestrated through predefined code paths"* vs *"dynamically direct their own processes and tool usage."* — Anthropic.
- *"Building the right system for your needs,"* not the most sophisticated. — Anthropic.
- Tools are *"the contract between the agent and the action space."* — Anthropic.
- In-context learning *"reduces an AI problem to a data engineering problem."* — a16z.
- *"If you ship LLM features without evals, you're guessing."* — Pragmatic Engineer.
- *"From vibes-based testing to a metrics-driven approach."* — Google Cloud.

Synthesized (label as yours, not quotes):
- **"From training models to orchestrating behavior."**
- **"The model is a frozen API; the product is everything around it."**
- **"Prompts (and tools and context) are the new hyperparameters; evals are the new test set."**
- **"MLOps stops at the model boundary; AgentOps starts there."**
- **"You no longer specify the pipeline — you constrain a system that writes its own."**

---

## 5. Caveats to stay honest

- **LLMOps ⊇ MLOps** — extends, doesn't replace. Still need CI/CD, versioning, monitoring, governance — more of it, in different places.
- **LLM-as-judge is a tool, not truth** — misses cross-turn/state defects (1-in-5 study). Pair with human calibration.
- **a16z is 2023** — stack diagram good, agent verdict stale.
- **AgentOps content is ~90% definitional marketing.** Substantive core (full-execution-graph tracing, per-session cost modeling, runtime policy enforcement, bad-*action* vs bad-*prediction*) is real; the "next frontier" packaging is not.

Read in full before the talk: the two **Anthropic** posts, the **AWS MLOps-vs-GenAI** post, **Thinking Machines** on non-determinism, **Catching One in Five**.
