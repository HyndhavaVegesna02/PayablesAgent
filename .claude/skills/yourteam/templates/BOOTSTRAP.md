# Bootstrap payload

What setup generates into a project, from this directory.

| Source | Destination | Rule |
|---|---|---|
| `agents/yt-*.md` | `.claude/agents/` | Copy. Defaults: implementer `sonnet`/`high`, reviewer `inherit`/`xhigh`. The implementer's `sonnet` is a family alias, which resolves to the newest Sonnet your allowlist permits — change it only to move the role to another family, never to chase a version. The reviewer inherits the session's model and overrides only effort. |
| `hooks/yt_git_guard.py` | `.claude/hooks/` | Copy |
| `hooks/settings-fragment.json` | `.claude/settings.json` | **Merge** the hooks block; never overwrite. Confirm first — hooks affect permissions. |
| `config.yaml`, `backlog.yaml`, `batch.yaml`, `definition-of-done.md`, `rules.md`, `rules-log.md`, `review-checklist.md` | `.yourteam/` | Copy; fill config from the detected environment |
| `change.md` | used as the template for `docs/changes/` | Not copied |

Never copied: `scripts/` and `references/`. They run from the skill directory
and read project state, so a fix reaches every project at once.

Two frontmatter options worth considering per project, both left off by default:

- `memory: project` on the reviewer gives it a directory under `.claude/agent-memory/` that survives across sessions, so it accumulates the recurring issues it keeps finding in this codebase. That is a second self-evolution channel alongside the rules ledger — quieter, since nothing approves what it writes. Turn it on if you want it; know that it is unaudited.
- `isolation: worktree` on the implementer, only when running changes concurrently. It costs a checkout per dispatch and is wasted otherwise.

The hook reads `batch.yaml` for the branch name. If the human declines hooks or
the environment can't run them, R003's prose is the fallback — note the
degradation once and move on.
