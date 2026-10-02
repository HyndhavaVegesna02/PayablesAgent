# Beyond the Prompt: Engineering Agents You Can Trust
`````
```

## Introduction

Six months ago we asked a simple question:

> **Can you build an autonomous agent?**

Most teams answered **yes**.

We saw planners, tool use, MCP servers, reasoning loops, RAG pipelines, and multi-agent systems. Building an agent is no longer the difficult part.

This year we're asking a different question:

> **Can you engineer one?**

Everyone has access to powerful models. What separates great systems today isn't the model itself — it's everything around it.

- Can it recover?
- Can you trust it?
- Can another engineer debug it?
- Can it fail safely?

That's what this hackathon is about.

---

## What You're Actually Building: a Harness

One reframe, up front, because the rest of this document depends on it.

The thing you are building is not "an agent." It's a **harness** — the scaffolding around the model that decides whether it succeeds or fails. It has four parts:

1. **The agent loop** — how it decides what to do next
2. **The tool interface** — what it can reach, and how failures come back
3. **Context management** — what's in the window, and what you're willing to lose
4. **Control mechanisms** — the rules that run whether or not the model cooperates

You will not beat anyone on model choice. You all have the same models. You will win or lose on the harness.

The harness is also the part that's reusable. A good permission layer, trace format, eval runner or state-handoff pattern transfers to your next project. The agent itself usually doesn't.

If you can't point at each of those four elements in your own code, you've built a script with a model in it. That's the bar this hackathon is trying to move you past.

---

## The North Star

By the end of this hackathon, we don't expect everyone to have built the next Claude Code.

We do expect everyone to understand what it takes to build an agent another engineer would be comfortable running in production.

Great agents aren't just intelligent. They are observable, measurable, safe, reliable, and maintainable.

---

# The Five Engineering Challenges

Each of these is short on purpose. Depth, mechanisms and worked detail are in **Field Notes** at the end — read those for whatever you're stuck on, not before you start.

## 1. Can your agent work without you?

Move beyond request-response demos.

Your agent should plan, choose tools, recover from failures, pause for human input, resume after interruptions where appropriate, and expose meaningful progress.

The practical test: pick a workflow big enough that the agent has to *work at it*. Several tool calls. Decisions that depend on what it found two steps ago. At least one thing going wrong. A task finished in a single model round-trip isn't a submission.

Keep the scope narrow. A small workflow done properly is the assignment; a broad one held together by prompts is not.

**Evidence** — demo · architecture · agent loop explanation

→ *Field Notes 1: state externalisation, sub-agent isolation*

---

## 2. Can another engineer debug it?

If your agent made a bad decision next Monday, could someone explain why?

Provide traces, tool history, reasoning and failures — enough to reconstruct what happened without re-running anything. Tool calls, arguments, intermediate outputs, retries and cost should all be recoverable from your own logs.

The test we'll actually apply: hand your trace to someone who didn't build the agent and ask them what went wrong. If they need you in the room, it isn't observable yet.

**Evidence** — success trace · failure trace · debugging walkthrough

→ *Field Notes 2: what belongs in a trace*

---

## 3. Does it actually work?

One successful demo isn't enough.

Show representative evaluation scenarios, success metrics, and at least one improvement that came out of your evaluation process.

Final-answer pass/fail is the weakest eval you can build. Look at whether the task succeeded, whether the *path* was sound, and which component broke when it didn't. Run each scenario more than once — one lucky run is not a result.

We're not setting a case count. Enough cases that a regression can't hide is the standard.

**Evidence** — eval report · one regression your suite caught

→ *Field Notes 3: the three levels, variance, judge calibration*

---

## 4. What happens when someone attacks it?

Traditional software engineers already know one rule:

> Never trust your inputs.

Demonstrate prompt injection awareness, permission boundaries, human approval for sensitive actions, and thoughtful risk management.

Nobody expects immunity — prompt injection can't be fully eliminated. We're judging **defence depth**: sandboxing, argument validation, filtering retrieved content, contained blast radius. So attack your own agent. Plant an injection where it will read one. Write up what happened.

**Evidence** — one-page threat model · permission model · one documented attack attempt and its outcome

→ *Field Notes 4: the lethal trifecta, approval fatigue, gating on intent*

---

## 5. Would you hand this to another team?

Explain your architecture, trade-offs, modularity and engineering decisions.

Simple, well-engineered systems beat overly ambitious demos.

The specific thing we're looking for: anything you cannot afford the agent to ignore — destructive-command blocking, PII redaction, loop detection, time budgets — should live in code that runs regardless of what the model decides. Prompt text is a suggestion. A hook is a guarantee.

**Evidence** — architecture writeup · your control layer · the trade-offs you made and why

→ *Field Notes 5: control points, tool design as UX*

---

# The One Required Artifact: the Harness Ablation

If you do nothing else on this list, do this.

**Hold the model fixed. Strip your harness down to a naive loop — all tools exposed, no hooks, no state file, no verification. Run your evals. Then run them again with the full harness. Report the delta.**

It's roughly thirty minutes of work and it's the most valuable thing you will produce. It tells you, with numbers, on your own task, how much of your agent's competence is the model and how much is your engineering. Report per component if you can: which single harness element bought you the most?

This is required because it's the fastest way to actually learn harness engineering rather than read about it. A team reporting "our harness added six points, and the state file did most of the work" has understood the discipline better than a team with a prettier demo.

For what this looks like at scale: [Improving Deep Agents with Harness Engineering](https://blog.langchain.com/improving-deep-agents-with-harness-engineering/) — rank 30 to top 5, no model swap.

---

# What You Have to Submit vs. What Wins

## The floor — four things

Meet these and you're a valid submission:

1. **A working agent** that completes a real workflow end to end, unattended — with a repo and a README someone else can run
2. **Two traces** — one success, one failure
3. **An eval report** — your scenarios, your results, and the harness ablation
4. **A one-page threat model** — including one attack you ran against your own agent

That's it. Four artifacts, most of them a page.

## What wins

Depth across the five challenges, and evidence over polish. A rough-edged agent with a real eval suite and a survivable failure mode beats a beautiful demo that falls over when we unplug it.

The full submission list, if you're going for it:

| Deliverable | What we're looking for |
|---|---|
| Repository + README | Runnable by someone who isn't you |
| Architecture diagram | Agent loop, tools, context management, control points — labelled |
| Evaluation report | Scenarios, results across repeated runs, one regression caught |
| **Harness ablation** | Naive vs. full harness, same model, and which component earned the most |
| Execution traces | One success, one failure |
| Threat model | One page, plus your attack attempt and its outcome |
| Permission model | What the agent and each sub-agent can touch |
| Demo video | 3 minutes |

**One extra ask:** flag **one harness component you think is reusable** — a trace format, a permission layer, an eval runner, a hook library. Anything another team could lift into a different project next quarter. We're collecting these into an internal library. That's how a hackathon stops being a weekend and starts being an asset.

---

# Going Beyond

Stretch goals:

- Durable execution
- Long-running agents
- Context engineering
- Advanced harness engineering
- Memory
- MCP
- Multi-agent systems
- Cost optimisation
- Cloud deployment

Two conditions. If you claim **memory**, beat a plain filesystem baseline — if the framework doesn't beat a directory of markdown files, say so; that's a real finding. If you go **multi-agent**, bring a defended reason: at 99% per-step reliability, a 50-step workflow still fails four times in ten.

---

# Team Rules & Constraints

- Team size = **2**
- Members must **not** be from the same project — cross-team collaboration encouraged
- Not part of GrokFest; no restrictions based on GrokFest participation
- **No client data. No client code.** No exceptions.
- Any tech stack — your choice of models, frameworks, MCP servers, agent SDKs
- Local hosting is completely fine (extra credit for cloud)
- AI coding assistants are encouraged — but **you** own the architecture decisions, and you'll be asked to defend them live

---

# Timeline

| Date | Milestone |
|---|---|
| **Fri Aug 21** | Team registration deadline |
| **Fri Sep 4** | Idea + high-level spec due — including threat model and eval plan |
| **Fri Sep 11** | Core team feedback returned — go / rescope / merge |
| **Fri Sep 25** | Optional checkpoint + office hours |
| **Fri Oct 2** | Code submission for review |
| **Mon–Thu Oct 5–8** | Core team review + scoring |
| **Fri Oct 9** | **Demo Day** |

**The Sep 11 gate is the most useful date on this list.** "Your eval plan is actually just manual spot-checking" is fixable in week 5 and fatal in week 9. Take the feedback seriously.

Two optional 45-minute sessions in September — one on evals, one on durability. Those are the two areas people most reliably underestimate.

---

# Judging

Scored against the five challenges, weighted toward evidence over polish. Demo day includes live Q&A; expect to be asked why you made a specific trade-off.

**Two awards.** Overall winner, plus **Best Harness** — for the team whose scaffolding is most worth stealing, judged on the ablation numbers and on reusability rather than on how impressive the agent looks. You can win Best Harness with a boring agent and excellent engineering.

Detailed rubric follows shortly. Core team announced separately; if you'd like to be on it, talk to your Engineering Manager.

---

# Reading

Nine links to start. The full categorised list is in Appendix B — go there when you're stuck on something specific, not before.


**Two hubs, for when you're stuck:**

- [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) — curated and organised by the problem each component solves
- [RUCAIBox/awesome-agent-harness](https://github.com/RUCAIBox/awesome-agent-harness) — the academic complement

**Two foundations — read these first:**

- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — Anthropic. When to use a workflow vs. an agent. Everything else assumes it.
- [How Claude Code Works](https://code.claude.com/docs/en/how-claude-code-works) — the official docs for the harness you already use every day.

**One per challenge, for when you get there:**

1. [The Anatomy of an Agent Harness](https://blog.langchain.com/the-anatomy-of-an-agent-harness/) — the clearest structural map of the loop you'll find
2. [Durable Execution for AI Agent Runtimes](https://zylos.ai/research/2026-04-24-durable-execution-agent-runtimes/) — and the distinction that matters: a trace explains what happened, a journal decides what may be replayed
3. [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — why unit-test-style evals fail for agents
4. [Agentic AI Security: Prompt Injection and the Defense Stack](https://zylos.ai/research/2026-05-16-agentic-ai-security-prompt-injection-defense-stack/) — seven layers, in risk order
5. [Harness Engineering](https://openai.com/index/harness-engineering/) — OpenAI. Why the scaffolding decides the outcome.

**And do this, which is worth more than any of the above:** for one week, stop using Claude Code as a tool and start reading it as a harness. Run `/context` mid-session and see what's eating your window. Watch what survives a compact and what quietly doesn't. Notice when a sub-agent saves you and when it costs you. Every mechanism you observe is one you might build yourself.

---

# Closing

There are plenty of hackathons where the goal is to build the most impressive AI demo.

This isn't one of them.

We'd rather see a narrow agent that's engineered well than a broad agent held together by prompts.

If your submission teaches another engineer a better way to build agents, you've already succeeded.

Let's build something we'd be proud to put into production — not because it's perfect, but because we understand how it works.

---
---

# Appendix: Field Notes

Read the section for whatever you're stuck on. Nobody needs all of this.

## 1 — Working without you

**Write your state down.** If the plan exists only in conversation history, it doesn't survive a restart, a compaction, or a Monday morning. Claude Code's memory is the filesystem and git, not the transcript: the plan is in a file, decisions are in a markdown doc, progress is in the diff, verification is a command you can re-run. An externalised state file — plan, status, completed work, blockers, next action — is the single highest-leverage thing in this appendix, and rehydrating from it should be the first move of every new session.

**Isolate sub-agent context.** A sub-agent gets a fresh window and returns a summary. The 4,000-line stack trace, the fifteen grep hits and every dead end stay in the child and never reach the parent. This is the main reason long sessions work at all.

**Know when *not* to run long.** A bigger context window doesn't fix context rot. New task, new session.

## 2 — Debuggability

A useful trace has: every tool call with its arguments, what came back, the model's stated reasoning at decision points, retries and their causes, and token count and cost per step. Timestamps throughout.

The distinction worth internalising: a **trace** is for humans reconstructing what happened. A **journal** is for machines deciding what may safely be replayed. They have different requirements, and conflating them is why "resumable" agents often aren't. If you're going for durability as a stretch goal, you need both.

## 3 — Evaluation

**Three levels.** *End-to-end* — did the task succeed? *Trajectory* — was the path sound? Wrong tool then recovered? Loops? Wasted calls? *Component* — which retriever, tool or sub-agent actually broke? Most teams only build the first and then can't explain their own failures.

**Variance.** Run each case several times and report success rate, spread and worst case. Agents are stochastic; a single run tells you almost nothing.

**If you use an LLM as a judge**, calibrate it against human labels on a subset and tell us the agreement rate. An uncalibrated judge is a confident random number generator.

**Wire evals into CI** if you can. A suite you have to remember to run is a suite that stops getting run around week 7.

## 4 — Adversarial

**The lethal trifecta.** Risk emerges from combinations, not single tools. When one agent has (1) access to private data, (2) exposure to untrusted content, and (3) the ability to communicate externally, you have an exfiltration path — no matter how safe each capability looks alone. Audit for it. If all three live in one context, say so in your threat model and explain what breaks the chain.

**Approval fatigue.** Anthropic found users approve roughly 93% of permission prompts, which makes the prompt decorative. If your design asks a human to confirm everything, you've built a rubber stamp. Ask rarely, ask about things that genuinely matter, and make the rare ask impossible to ignore. See [Beyond Permission Prompts](https://www.anthropic.com/engineering/beyond-permission-prompts).

**Gate on intent, not command names.** `rm`, `curl` and `psql` are each harmless or catastrophic depending on their arguments. An allow-list of binaries is not a permission system. Classify what an action *does*: read, write, delete, outbound network, code execution.

**Confirm out of band.** If your agent asks "shall I send this?" through a surface the agent itself controls, an attacker who owns the agent's context owns the confirmation too.

**Sub-agents inherit a subset, not a copy.** Check your framework's default — several copy, and a permissive flag on a parent can propagate silently.

## 5 — Handing it over

**Control points.** Deterministic policy at lifecycle boundaries — before-model, before-tool, after-tool, after-agent — rather than rules written into a system prompt and hoped for. Each hook should be able to emit allow / deny / require-approval / mask, and write an audit record either way.

**Tool design is agent UX.** Naming, schemas, and especially *error surfaces*: a bad error message costs three wasted turns. Annotate each tool — read-only, destructive, idempotent, reaches the open world — because those annotations are what your permission layer reasons over.

**Verification, split two ways.** *Computational* controls (linters, tests, schema validation) are cheap and exact. *Inferential* controls (LLM-as-judge) are flexible and fallible. Use both, and let the agent catch its own mistakes before a human sees the output.

**Version the harness.** Anthropic traced a visible Claude Code quality regression this April to three harness changes — a reasoning-effort default, a caching bug, an over-aggressive verbosity instruction. No model changes. If a prompt tweak can regress your agent, it needs the same change control as your code, and your eval suite is how you'd catch it.

---

# Appendix B: Full Reading List

Organised by challenge. Skim the section for whatever you're stuck on — you are not expected to read all of this, and nobody will.

## Two hubs worth bookmarking

- [awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) — curated, actively maintained, organised by the problem each component solves rather than by vendor. If you read one index, make it this one.
- [RUCAIBox/awesome-agent-harness](https://github.com/RUCAIBox/awesome-agent-harness) — the academic complement: a survey paper plus 500+ references across harness design, memory, skill libraries and orchestration.

---

## Foundations

- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — Anthropic. When to use a workflow vs. an agent, and how to compose primitives. Everything else assumes it.
- [Harness Engineering](https://openai.com/index/harness-engineering/) — OpenAI. What the discipline is, and why the scaffolding decides success rather than the model.
- [The Anatomy of an Agent Harness](https://blog.langchain.com/the-anatomy-of-an-agent-harness/) — LangChain's five primitives: filesystem, code execution, sandbox, memory, context management. The clearest structural map available.
- [How Claude Code Works](https://code.claude.com/docs/en/how-claude-code-works) — official docs for the harness you already use daily. Compaction, subagents, skills-on-demand, checkpoints, permissions.
- [Harness Engineering](https://martinfowler.com/articles/exploring-gen-ai/harness-engineering.html) — Martin Fowler: context engineering plus architectural constraints plus entropy management, and the "humans *on* the loop" framing.
- [Harness Engineering for Coding Agent Users](https://martinfowler.com/articles/harness-engineering.html) — Birgitta Böckeler: feedforward guides plus feedback sensors, and the computational vs. inferential control split.
- [Harness Engineering: Structured Workflows](https://developers.redhat.com/articles/2026/04/07/harness-engineering-structured-workflows-ai-assisted-development) — Red Hat's enterprise take.
- [Harness Engineering: Engineering the System, Not the Model](https://www.deepset.ai/blog/harness-engineering) — deepset's failure-classification framework: context / constraint / verification / planning failures.
- [A Practical Guide to Building AI Agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) — OpenAI, April 2026.
- [The Coding Harness Behind GitHub Copilot in VS Code](https://code.visualstudio.com/blogs/2026/05/15/agent-harnesses-github-copilot-vscode) — how a major product treats harness changes as first-class code review.

**If you want the formal definitions:**

- [What Makes a Harness a Harness](https://arxiv.org/abs/2606.10106) — the four necessary and sufficient elements.
- [Architectural Design Decisions in AI Agent Harnesses](https://arxiv.org/abs/2604.18071) — empirical study across 70 public agent systems.
- [The Design Space of Today's and Future AI Agent Systems](https://arxiv.org/abs/2604.14228) — reverse-engineers Claude Code: five-stage progressive compaction and a 27-event hook pipeline.

---

## Challenge 1 — Working without you

**The agent loop:**

- [ReAct](https://arxiv.org/abs/2210.03629) — the original Thought/Action/Observation loop. Still worth 20 minutes.
- [Unrolling the Codex Agent Loop](https://openai.com/index/unrolling-the-codex-agent-loop/) — OpenAI's decomposition of a single iteration: observe, plan, act, verify.
- [LangGraph Low-Level Concepts](https://langchain-ai.github.io/langgraph/concepts/low_level/) — the loop as a typed graph with checkpointing.
- [Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking) — read the part about preserving thinking blocks when returning tool results *before* you debug a mysterious multi-step failure.
- [statewright](https://github.com/statewright/statewright) — state-machine guardrails; the 2/10 to 10/10 result on a SWE-bench subset from constraining which tools were callable per phase.

**State, recovery and session boundaries:**

- [Session Management and 1M Context](https://claude.com/blog/using-claude-code-session-management-and-1m-context) — including when *not* to keep a long session going.
- [Claude Code Compaction Explained](https://okhlopkov.com/claude-code-compaction-explained/) — what survives a compact and what quietly doesn't.
- [Introducing Dynamic Workflows in Claude Code](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code) — the plan living in executable code rather than the context window.
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — initializer-agent to worker-agent handoff, with feature lists, commits and test gates as the durable state.
- [Run Long-Horizon Tasks with Codex](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex/) — `Plan.md` / `Implement.md` as harness artifacts.

---

## Challenge 2 — Debuggability

- [Durable Execution for AI Agent Runtimes](https://zylos.ai/research/2026-04-24-durable-execution-agent-runtimes/) — and the distinction that matters most here: a trace explains what happened, a journal decides what may be replayed.
- [Durable Execution for LLM Agents: Temporal + LangGraph](https://appscale.blog/en/blog/durable-execution-llm-agents-temporal-langgraph-checkpointing-2026) — the replay-safety contract, idempotency key derivation, resumable SSE.
- [LLM Readiness Harness: Evaluation, Observability and CI Gates](https://arxiv.org/abs/2603.27355) — observability wired into deployment gates rather than bolted on.
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — debug your MCP server without standing up a full agent.

---

## Challenge 3 — Evaluation

- [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — Anthropic. Start here; it explains why unit-test-style evals fail for agents.
- [LLM Agent Evaluation: Complete Guide](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide) — the three levels (end-to-end / trajectory / component) with metrics for each.
- [Evaluating AI Agents: Trajectory & Tool-Use Evals](https://appscale.blog/en/blog/evaluating-ai-agents-trajectory-tool-use-evaluation-2026) — safety invariants plus rubric scoring, N-run variance, and running the suite as a CI release gate.
- [LLM-as-Judge Patterns: Calibration, Bias, Trajectory](https://zylos.ai/research/2026-05-26-llm-as-judge-agent-evaluation-patterns/) — if you use a judge, calibrate it; this tells you how.
- [AdaRubric: Task-Adaptive Rubrics](https://arxiv.org/pdf/2603.21362) — task-specific rubrics correlate with human judgment far better than one static rubric.

---

## Challenge 4 — Adversarial hardening and permissions

**Security:**

- [Agentic AI Security: Prompt Injection, Tool Hijacking, and the Defense Stack](https://zylos.ai/research/2026-05-16-agentic-ai-security-prompt-injection-defense-stack/) — the seven-layer defence model, and a risk-based order to implement it in.
- [Prompt Injection Defense: Complete 2026 Guide](https://sureprompts.com/blog/prompt-injection-defense-complete-guide-2026) — read the section on out-of-band confirmation.
- [Prompt Injection Risks: A Claude Code Guide for Enterprise Teams](https://www.truefoundry.com/blog/claude-code-prompt-injection) — concrete, uncomfortable, useful.
- [How to Sandbox AI Agents](https://northflank.com/blog/how-to-sandbox-ai-agents) — microVMs, gVisor, Kata; resource limits and network controls.
- [Agent Skills: Architecture, Acquisition, Security](https://arxiv.org/html/2602.12430v3) — why skills are a novel attack surface: natural language plus executable code the agent trusts implicitly.
- OWASP's agentic material lives at [genai.owasp.org](https://genai.owasp.org/) — find the Top 10 for Agentic Applications there. ASI01 Goal Hijacking is the one that matters most for us.

**Permissions and authorization:**

- [Beyond Permission Prompts](https://www.anthropic.com/engineering/beyond-permission-prompts) — structured authorization instead of prompt-level trust.
- [Claude Code Auto Mode](https://www.anthropic.com/engineering/claude-code-auto-mode) — the 93% approval-fatigue finding, plus deny-and-continue over halt.
- [Claude Agent SDK: Configure Permissions](https://platform.claude.com/docs/en/agent-sdk/permissions) — the five-layer evaluation order, and the subagent inheritance warning.
- [OWASP LLM06: Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) — the audit checklist for over-provisioned agents.
- [Two Different Types of Agent Authorization](https://blog.langchain.com/two-different-types-of-agent-authorization/) — on-behalf-of vs. fixed-credential; entirely different threat surfaces.
- [nah](https://github.com/manuelschipper/nah) — intent-taxonomy enforcement instead of command allow-lists.
- [Open Agent Passport](https://arxiv.org/abs/2603.20953) — pre-action authorization with signed audit records; 0% vs. 74.6% attack success under restrictive vs. permissive policy.
- [Runtime Authorization Beyond Identity](https://techcommunity.microsoft.com/blog/microsoft-security-blog/authorization-and-governance-for-ai-agents-runtime-authorization-beyond-identity/4509161) — Microsoft's PEP/PDP fabric returning ALLOW / DENY / REQUIRE_APPROVAL / MASK.
- [Governing Agents](https://wellarchitected.github.com/library/governance/recommendations/governing-agents/) — GitHub's enterprise guide.
- *Extra credit:* [IETF draft-klrc-aiagent-auth](https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/) — the first standards-track spec for agent auth, built on OAuth token exchange and DPoP.

---

## Challenge 5 — Handing it to another team

**Control mechanisms:**

- [How Middleware Lets You Customize Your Agent Harness](https://blog.langchain.com/how-middleware-lets-you-customize-your-agent-harness/) — six composable hooks; the reference design for policy you can't trust to a prompt.
- [Codex Hooks](https://developers.openai.com/codex/hooks) — deterministic scripts at `SessionStart`, `PreToolUse`, `PostToolUse`.

**Tool design:**

- [Writing Effective Tools for Agents](https://www.anthropic.com/engineering/writing-effective-tools-for-agents) — tool design *is* agent UX: naming, schemas, error surfaces.
- [Tool Annotations as Risk Vocabulary](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) — `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`, and the lethal trifecta. Relevant to challenges 4 and 5 both.
- [Tool Use Overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) — client vs. server execution models.
- [Function Calling](https://platform.openai.com/docs/guides/function-calling) — the de facto schema conventions.

**Why you version the harness:**

- [An Update on Recent Claude Code Quality Reports](https://www.anthropic.com/engineering/april-23-postmortem) — three harness-level changes, zero model changes, a visible regression. Read this before you tweak a system prompt on Oct 1.

---

## The ablation — what it looks like at scale

- [Improving Deep Agents with Harness Engineering](https://blog.langchain.com/improving-deep-agents-with-harness-engineering/) — rank 30 to top 5 on Terminal Bench 2.0 with no model swap: verification loops, directory maps injected into context, loop-detection middleware, reasoning budget concentrated at planning and verification.
- [Context Engineering Lessons from Building Azure SRE Agent](https://techcommunity.microsoft.com/blog/appsonazureblog/context-engineering-lessons-from-building-azure-sre-agent/4481200/) — 100+ bespoke tools and a prescriptive prompt replaced by plain files plus `grep`, `find` and `read_file`; intent-met rate on novel incidents went from 45% to 75%. See also [the architecture walkthrough](https://techcommunity.microsoft.com/blog/appsonazureblog/how-we-build-azure-sre-agent-with-agentic-workflows/4508753) covering 35,000+ production incidents.

---

## Stretch: durable execution and long-running agents

- [Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps) — Anthropic.
- [Shell + Skills + Compaction: Tips for Long-Running Agents](https://developers.openai.com/blog/skills-shell-tips) — OpenAI.
- [Meta's Ranking Engineer Agent](https://engineering.fb.com/2026/03/17/developer-tools/ranking-engineer-agent-rea-autonomous-ai-system-accelerating-meta-ads-ranking-innovation/) — hibernate-and-wake checkpointing for multi-day pipelines.
- [Building Durable AI Agents with Temporal](https://niteagent.com/blog/2026-06-29-durable-ai-agents-temporal-guide/) — working code, five patterns.

---

## Stretch: context and cost

- [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — Anthropic. Context as a finite curated resource rather than a prompt you write once.
- [Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) — progressive disclosure and `search_tools`; large token reductions.
- [Compaction API](https://platform.claude.com/docs/en/build-with-claude/compaction) — server-side, configurable thresholds.
- [Prompt Caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) — the cheapest cost lever available to you; read the `cache_control` placement guidance.
- [Autonomous Context Compression](https://blog.langchain.com/autonomous-context-compression/) — agent-triggered compression instead of compacting mid-subtask.
- [Context Engineering: A Practical Guide](https://sourcegraph.com/blog/context-engineering) — Sourcegraph's retrieval numbers, including a 2-hour timeout becoming 89 seconds.
- [Token Savior](https://github.com/Mibayy/token-savior) — navigate by symbol instead of reading whole files.

---

## Stretch: MCP, skills and protocols

- [Model Context Protocol](https://modelcontextprotocol.io/introduction) · [reference servers](https://github.com/modelcontextprotocol/servers) · [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [The 2026 MCP Roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/) — read this before betting infrastructure on current transport behaviour.
- [Microsoft Skills Framework](https://github.com/microsoft/skills) — skills as versioned, portable artifacts.
- [A2A Protocol](https://github.com/a2aproject/A2A) · [Agent Discovery / Agent Cards](https://a2a-protocol.org/latest/topics/agent-discovery/)
- [Developer's Guide to AI Agent Protocols](https://developers.googleblog.com/en/developers-guide-to-ai-agent-protocols/) — which protocol for which boundary.
- [agentgateway](https://github.com/agentgateway/agentgateway) — unified LLM/MCP/A2A control plane.
- [Choosing the Right Multi-Agent Architecture](https://blog.langchain.com/choosing-the-right-multi-agent-architecture/) — subagents vs. skills vs. handoffs vs. router, with token data.
- [Multi-Agent Workflows Often Fail — Here's How to Engineer Ones That Don't](https://github.blog/ai-and-ml/generative-ai/multi-agent-workflows-often-fail-heres-how-to-engineer-ones-that-dont/) — treat handoffs as distributed-systems interfaces.

---

## Stretch: memory

- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) — multi-signal retrieval (semantic + BM25 + entity) and where the gains actually come from.
- [AI Agent Memory Architectures](https://zylos.ai/research/2026-04-05-ai-agent-memory-architectures-persistent-knowledge/) — the episodic / semantic / procedural taxonomy and current benchmarks.
- [Best AI Agent Memory Frameworks 2026](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/) — comparison, and which to pick for what.
- [Letta](https://github.com/letta-ai/letta) · [mem0](https://github.com/mem0ai/mem0) · [Zep](https://github.com/getzep/zep)
- Remember the condition: you must beat a plain filesystem baseline to claim points here. Letta's own benchmarking suggests that's harder than it sounds.

---

## Stretch: moonshot

- [Awesome Self-Evolving Agents](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents) — survey plus curated papers.
- [Next-Generation Agentic RL Systems Enable Self-Evolving Agents](https://arxiv.org/abs/2607.01120) — July 2026 position paper; argues the blocker is systems, not algorithms.
- [SkillOpt](https://github.com/microsoft/SkillOpt) — skills as optimisable parameters improved by execution feedback, not static prose.

---

*Links current as of early August 2026. If one has rotted, the two hub repos at the top of this appendix are the fastest way to find the replacement.*