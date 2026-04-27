# AutoResearch — Definitive Codebase Report (April 27, 2026)

**Repository:** [uridolan77/AutoResearch](https://github.com/uridolan77/AutoResearch)  
**HEAD commit:** `87871eea` (April 26, 2026 21:21 UTC)  
**Scope:** All current backend files read directly from source; frontend, config, Docker, and LLM subsystem fully verified.  
**Build phase:** Phase 1, Days 1–8 complete. CLI validation gate (Day 10) is imminent.

***

## Architecture Summary

AutoResearch is a generalized autonomous-improvement platform built on the Karpathy ratchet-loop pattern: an LLM proposer generates diffs, they are validated and applied to a git worktree, a sandboxed evaluator scores them, and a human (or automated policy) decides keep/revert. The platform is organized as a FastAPI REST/WebSocket backend with a Celery task chain, a React/TypeScript frontend, and a comprehensive `docs/architecture.md` specification that preceded the implementation.

The full backend task chain is:

```
loop → plan → apply_edit → run_experiment → score
                                                 ↓
                                    decide (fresh task, idempotent)
                                                 ↓
                                              loop (re-enqueues)
```

All five services are orchestrated via Docker Compose: `redis`, `migrate` (Alembic), `api` (FastAPI/uvicorn), `worker` (Celery, `--concurrency=2`), and `beat` (Celery Beat, hourly `stale_reviews`).

***

## Implementation Status: What Is Confirmed Working

### ✅ Full Task Chain Is Wired and Correct

- **`loop.py`**: Correctly gates on session status `{running, idle}` and enforces the token-escape fix (session `tokens_used >= token_cap_session` → drain before re-enqueueing `plan`). The pause/drain/stop/complete early-return is correct.
- **`apply_edit.py`**: Full validation + retry loop (up to `validation_retry_max`), diff sanitization, deduplication hash check, worktree creation, and `celery_app.send_task("autoresearch.loop")` re-enqueue on **all** failure paths (validation exhausted, duplicate, git-apply failure). The best-effort `gitsvc.remove_worktree()` cleanup on git-apply failure is in place.
- **`run_experiment.py`**: Handles missing evaluator row and secret decryption failure with explicit `loop` re-enqueue and `short_circuit`. Evaluator exceptions are caught, journaled, and re-enqueue loop.
- **`score.py`**: First-iteration semantics are correct — when no prior kept experiment exists, `score_before = score_after` so `delta=0`, and the first experiment is routed for human review (not auto-rejected) under `improvements_only` mode. `review_mode` routing table is implemented correctly.
- **`decide.py`**: `_enqueue_loop` helper is called on all terminal paths including merge failure and revert failure. Worktree pruning and token-drain check are in place.
- **`stale_reviews.py`**: Hourly Beat task correctly scans `awaiting_review` experiments, handles naive/UTC datetime comparison, writes synthetic `rejection_comment`, and calls `send_task("autoresearch.decide")`.
- **`app/llm/` router layer**: `AnthropicRouter` and `OpenAIRouter` are fully wired. `make_router()` selects by `settings.llm_provider`. `ProposerClient` and `JudgeClient` delegate to `_router().call()` via `@lru_cache` singleton.
- **`db.py`**: WAL mode, `PRAGMA foreign_keys=ON`, and `synchronous=NORMAL` are set via SQLAlchemy event listener.

***

## Critical Bugs (Session-Halting / Unrecoverable)

### #1 — `on_chain_error` Does NOT Re-Enqueue Loop *(Confirmed by direct read)*

The `on_chain_error` docstring was updated to say the re-enqueue fix is in, but the actual code ends after journaling with no `send_task` call:

```python
# on_chain_error — confirmed current code:
journal_append(session_id, "experiment_failed", {...})
# db.close() in finally
# NO send_task("autoresearch.loop", ...) here
```

Any unhandled exception in the chain — OOM in the evaluator container, an unexpected exception in `score`, a network error that escapes `EvaluatorError` — marks the experiment `failed` and **permanently halts the session**. Individual tasks (`run_experiment`, `apply_edit`) handle their own known errors and re-enqueue loop. But `on_chain_error` is the safety net for everything else, and it is broken.

**Fix (one line):** Add `celery_app.send_task("autoresearch.loop", args=[session_id])` after the `db.close()` block in `on_chain_error`.

***

### #2 — `decide` Uses `running` as Intermediate Status — No Recovery on Worker Death

`decide` atomically transitions `awaiting_review → running` as its idempotency guard:

```python
.update({Experiment.status: ExperimentStatus.running}, synchronize_session=False)
```

`ExperimentStatus.deciding` does not exist in `enums.py`. If the worker process is killed (SIGKILL, OOM) after this UPDATE but before the git merge or reset completes, the experiment is permanently stuck in `running`. Neither `stale_reviews` (which only queries `awaiting_review`) nor any other sweep ever recovers a `running` row that is not progressing.

**Fix:** Add `ExperimentStatus.deciding` to `enums.py` and a new Alembic migration. Use `deciding` as the intermediate status in `decide`. Add a Beat-triggered recovery sweep for experiments stuck in `deciding` for >N minutes.

***

### #3 — No `UniqueConstraint` on `(session_id, iteration)` — Race Condition Under Concurrency

`experiment.py`'s `__table_args__` uses only a non-unique `Index`:

```python
__table_args__ = (
    Index("ix_experiments_session_iteration", "session_id", "iteration"),
    Index("ix_experiments_session_diffhash", "session_id", "diff_hash"),
)
```

`plan.py` uses `SELECT MAX(iteration)` to compute the next iteration number. Two concurrent `plan` tasks for the same session will both read the same max and insert two experiments with duplicate `(session_id, iteration)`. Additionally, `context.py` makes its own independent `_next_iteration()` call to populate the iteration number in the LLM prompt — if an experiment is inserted between `plan`'s call and `context`'s call, the prompt shows a different iteration than the row's actual value.

**Fix:** Change the `Index` to `UniqueConstraint("session_id", "iteration")`, add a migration, and add retry-on-`IntegrityError` in `plan.py`.

***

### #4 — `task_acks_late=True` Without `task_reject_on_worker_lost=True` — Tasks Lost on Worker Death

`celery_app.py` sets `task_acks_late=True` but does not set `task_reject_on_worker_lost=True`. Under `task_acks_late`, messages are acknowledged only after the task completes. However, if the worker process is killed (SIGKILL), Celery acknowledges the task anyway rather than rejecting it back to the queue. The task is permanently lost — it will never be retried, and no `on_chain_error` fires because the process died.

**Fix:** Add `task_reject_on_worker_lost=True` to `celery_app.conf.update()`.

***

### #5 — LLM Routers Have No Timeout or Retry — Transient Errors Compound with #1

Both `AnthropicRouter.call()` and `OpenAIRouter.call()` make bare blocking API calls with no timeout parameter, no retry, and no backoff. A transient 429, 5xx, or network hang propagates as an unhandled exception to `on_chain_error`, which (per #1) does not re-enqueue the loop. The combination of #1 and #5 makes any transient LLM error permanently session-halting.

**Fix (independent of #1):** Pass `timeout=30` to the `anthropic.Anthropic()` and `openai.OpenAI()` constructors. Add a retry decorator (e.g., `tenacity.retry` with exponential backoff on 429/5xx). As a backstop, fix #1 so `on_chain_error` at least re-enqueues the loop regardless.

***

## High-Severity Issues

### #6 — `AnthropicRouter` Constructs with Empty Key Silently — No Startup Guard

`config.py` defines `secret_key: str = ""` and `anthropic_api_key: str = ""` with no `model_post_init` validation. The `model_post_init` that exists only creates directories. `AnthropicRouter.__init__` constructs `anthropic.Anthropic(api_key=settings.anthropic_api_key)` unconditionally — even when the key is `""`, the client object is created silently. The first actual API call returns an opaque 401 rather than a clear startup error.

This is a regression from the old `ProposerClient` which had a conditional key check. **Fix:** Add `@model_validator(mode="after")` in `Settings` that raises `ValueError` if `anthropic_api_key` (or `openai_api_key`, per provider) and `secret_key` are empty strings.

***

### #7 — `OpenAIRouter` Double-Nested Fallback Is Opaque and Unlogged

When `llm_provider=openai` and both `proposer_model` and `judge_model` are Claude names (the defaults), the proposer silently falls back to `gpt-4o-mini`:

```python
proposer_model = _normalize_openai_model(
    settings.proposer_model, fallback=_normalize_openai_model(settings.judge_model, fallback="gpt-4o-mini")
)
```

The behavior is correct (it prevents a `claude-sonnet-4-5` model name being sent to the OpenAI API), but there is no `logger.warning()` when the fallback fires. A developer who sets `AR_LLM_PROVIDER=openai` without updating `AR_PROPOSER_MODEL` will be silently using `gpt-4o-mini` for the proposer with no indication in logs.

**Fix:** Log a `WARNING` when `_normalize_openai_model` replaces a Claude name.

***

### #8 — Docker Compose: `--reload`, Docker Socket on `api`, Unauthenticated Redis

Three `docker-compose.yml` security issues are confirmed open:

| Issue | Detail |
|-------|--------|
| `--reload` on `api` | `uvicorn ... --reload` enables hot-reload and file-watching in what will be a production deployment. Leaks internal file paths and enables arbitrary file read abuse if the API surface is exploited. |
| `docker.sock` on `api` | `/var/run/docker.sock:/var/run/docker.sock` is mounted on both `api` and `worker`. The API process has full Docker daemon control. A compromised API endpoint can create/destroy containers on the host. The socket is only needed on `worker`. |
| Redis exposed without auth | Port `16379:6379` is exposed to the host with no `requirepass` and no `AR_REDIS_URL` password. Any process on the host can read/write the Celery task queue. |

***

### #9 — SQLite `busy_timeout` Not Set — Lock Errors Under `--concurrency=2`

`db.py` sets WAL mode and `synchronous=NORMAL` but does not set `PRAGMA busy_timeout`. SQLite's default lock timeout is driver-dependent and often 0 ms. With `--concurrency=2` in the worker, two Celery task threads can attempt simultaneous writes and raise `OperationalError: database is locked`. WAL mode reduces but does not eliminate write-write contention. **Fix:** Add `cur.execute("PRAGMA busy_timeout=5000")` (5 seconds) in the `_enable_sqlite_pragmas` event listener.

***

### #10 — `stale_reviews` Per-Row Commit/Enqueue — Stuck If Broker Hard-Fails

`stale_reviews` iterates rows, commits `decision` inside the loop, then calls `send_task`. As analyzed: if `send_task` raises a non-transient error (broker down), the row has `decision=auto_rejected_timeout` set but no `decide` task enqueued. On the next Beat tick, `stale_reviews` re-reads all `awaiting_review` rows regardless of whether `decision` is already set — it re-sets the decision (idempotent) and re-sends. So **in the transient-error case, the row will be retried on the next tick**, which is acceptable behavior. However, if the broker is **permanently** down, the row loops on every tick: decision is re-set but never actioned. A defensive fix is to batch all writes and only then iterate `send_task`, wrapping failures in a per-row try/except that leaves `decision` un-set for failed sends.

***

### #11 — `_prune_old_worktrees` Path Reconstructed by Convention — No Canonical Storage

In `decide.py`, `_prune_old_worktrees` assembles the worktree path as:

```python
wt_path = settings.worktree_root / f"session-{session.id}" / "exp" / exp.id
```

 The `Experiment` model has no `worktree_path` column. The actual worktree is created by `gitsvc.create_experiment_worktree()` in `apply_edit.py`, whose internal path scheme must match this convention. If `GitService` ever uses a different directory scheme, pruning silently fails and orphaned worktrees accumulate on disk. **Fix:** Store the worktree path in `Experiment.worktree_path` (nullable `String(512)`) at creation time and read it in `_prune_old_worktrees`.

***

## Medium-Severity Issues

### #12 — `_router()` `@lru_cache` Bleeds Across Tests and Prevents Runtime Provider Switch

`_router()` in `agent/llm.py` is `@lru_cache`. `get_settings()` is also `@lru_cache`. Both caches persist across test runs in the same process, causing settings/router state bleed between tests. No autouse fixture exists to clear them (tests directory is sparse). Additionally, if `AR_LLM_PROVIDER` is changed in a running process (e.g., during a test that patches env vars), the cached router silently ignores the change.

***

### #13 — `whitelist = (session.target_file,)` vs `max_files_per_diff > 1`

`apply_edit.py` hardcodes the validator whitelist to `(session.target_file,)` while `Session.max_files_per_diff` can be set up to the ceiling of 5. Sessions configured with `max_files_per_diff=2` or higher will have multi-file diffs rejected by the validator regardless, because only one file is permitted by the whitelist. The whitelist should either be extended (e.g., stored as `session.allowed_files` as a JSON list) or `max_files_per_diff` should be constrained to 1 when no extended allowlist is configured.

***

### #14 — `score.py` Silent `evaluator_row=None` Fallback

```python
direction = evaluator_row.direction if evaluator_row else MetricDirection.maximize
```
 If the evaluator row was deleted between `run_experiment` and `score`, `score` silently scores with `maximize` direction. `run_experiment` correctly fails-fast and re-enqueues loop on missing evaluator — `score` should do the same rather than silently using a wrong direction that could flip an auto-reject into an auto-approve.

***

### #15 — `wall_clock_budget_s` Is Dead Schema

`Session.wall_clock_budget_s` is defined in the model but no task reads or enforces it. `CommandEvaluator` has a `wall_clock_budget_s` field (from the evaluator row), but the session-level field is disconnected. This is a dead column that implies a feature that doesn't exist.

***

### #16 — `REJECTION_MAX_CHARS = 500` and `String(500)` Are Unlinked

`context.py` defines `REJECTION_MAX_CHARS = 500`; `experiment.py` uses `String(500)` for `rejection_comment`. Auto-generated rejection comments in `score.py` and `stale_reviews.py` could exceed 500 chars in edge cases (long model names, long delta values with many decimal places). One source of truth (a constant in `models/experiment.py` imported by both) would prevent drift.

***

## Low-Severity Issues

### #17 — `temperature` and `model` Parameters Silently Discarded in `agent/llm.py`

Both `ProposerClient.complete()` and `JudgeClient.complete()` accept `temperature` and `model` constructor arguments but discard them — `_ = temperature`; `self.model` is stored but not passed to `_router()`. Call sites in `apply_edit.py` pass `temperature=0.3` which is silently ignored. The router's stage `ModelConfig` owns the temperature, which is by design. A `logger.debug()` or docstring note when a non-default temperature is passed would prevent silent misconfiguration.

### #18 — `cached=False` Always — Dead Field in `LLMCallResult`

Both routers hardcode `cached=False` in `LLMCallResult`. The field exists presumably for Anthropic prompt caching. It is dead state. Either implement it or remove the field.

### #19 — `get_prompt_hash()` Defined but Never Called

`router.py` exports `get_prompt_hash()` but it is imported or used nowhere in the codebase. It was likely intended for LLM-layer deduplication in addition to the diff-hash dedup in `apply_edit`. It is dead code.

### #20 — Stale "Days 7-8" / "v3 loose end" Scaffolding Comments

Docstrings in `score.py`, `run_experiment.py`, and `loop.py` contain build-phase scaffolding language ("Days 7-8", "v3 loose end fix", "this is the seam") that implies the code is not production-ready and creates confusion about which items are actually resolved. These should be cleaned up before the Day 10 CLI gate.

### #21 — `node_modules` and `dist` Committed to Git

`frontend/node_modules` and `frontend/dist` are tracked in Git. This inflates clone size by thousands of files, makes diffs meaningless for those directories, and will slow any CI that checks out the repo. Add both to `.gitignore` and remove with `git rm -r --cached`.

### #22 — `ChainContext` TypedDict Is Unenforced

All task functions accept and return `dict[str, Any]` at runtime, not the `ChainContext` TypedDict. Missing keys or type errors in chain context assembly are invisible to mypy/pyright. No practical harm at runtime, but static analysis provides no safety net.

***

## Definitive Issue Table

| # | Severity | Issue | File | Status |
|---|----------|-------|------|--------|
| 1 | 🔴 Critical | `on_chain_error` does NOT re-enqueue loop — session halts on any chain crash | `run_experiment.py` | **Confirmed open** |
| 2 | 🔴 Critical | `decide` transitions to `running` not `deciding` — worker death creates permanent orphan | `decide.py` / `enums.py` | **Confirmed open** |
| 3 | 🔴 Critical | No `UniqueConstraint(session_id, iteration)` — duplicate experiments under concurrency | `experiment.py` | **Confirmed open** |
| 4 | 🔴 Critical | `task_acks_late=True` without `task_reject_on_worker_lost=True` — tasks lost on SIGKILL | `celery_app.py` | **Confirmed open** |
| 5 | 🔴 Critical | LLM routers have no timeout/retry — transient errors + #1 = permanent session halt | `anthropic_router.py` / `openai_router.py` | **Confirmed open** |
| 6 | 🟡 High | `AnthropicRouter` constructs with empty API key silently — regression from old guard | `anthropic_router.py` / `config.py` | **Confirmed open** |
| 7 | 🟡 High | `OpenAIRouter` double-nested fallback is opaque and unlogged | `openai_router.py` | **Confirmed open** |
| 8 | 🟡 High | Docker: `--reload` on `api`, `docker.sock` on `api`, unauthenticated Redis | `docker-compose.yml` | **Confirmed open** |
| 9 | 🟡 High | SQLite `busy_timeout` not set — lock errors under `--concurrency=2` | `db.py` | **Confirmed open** |
| 10 | 🟡 High | `stale_reviews` per-row commit/enqueue — stuck if broker permanently down | `stale_reviews.py` | **Open (mitigated by retry)** |
| 11 | 🟡 High | `_prune_old_worktrees` path reconstructed by convention — no canonical storage | `decide.py` / `experiment.py` | **Confirmed open** |
| 12 | 🟡 Medium | `_router()` `@lru_cache` bleeds across tests, prevents runtime provider switch | `agent/llm.py` | **Confirmed open** |
| 13 | 🟡 Medium | `whitelist=(target_file,)` vs `max_files_per_diff > 1` — multi-file sessions broken | `apply_edit.py` | **Confirmed open** |
| 14 | 🟡 Medium | `score.py` silent `evaluator_row=None` fallback flips direction silently | `score.py` | **Confirmed open** |
| 15 | 🟡 Medium | `wall_clock_budget_s` is dead schema | `session.py` | Open |
| 16 | 🟡 Medium | `REJECTION_MAX_CHARS` and `String(500)` unlinked — two sources of truth | `experiment.py` / `context.py` | Open |
| 17 | 🟢 Low | `temperature` and `model` params silently discarded in `ProposerClient`/`JudgeClient` | `agent/llm.py` | Open |
| 18 | 🟢 Low | `cached=False` always — dead field | `anthropic_router.py` / `openai_router.py` | Open |
| 19 | 🟢 Low | `get_prompt_hash()` dead code | `llm/router.py` | Open |
| 20 | 🟢 Low | Stale scaffolding comments ("Days 7-8", "v3 loose end") | multiple | Open |
| 21 | 🟢 Low | `node_modules` and `dist` tracked in Git | `frontend/` | Open |
| 22 | 🟢 Low | `ChainContext` TypedDict unenforced at runtime | `tasks/chain.py` | Open |

***

## What Has Been Confirmed Fixed vs Prior Review

| Prior Issue | Current Status |
|-------------|---------------|
| `apply_edit` doesn't re-enqueue loop on failure | ✅ **Fixed** — all three failure paths (validation, duplicate, git-apply) now call `send_task("autoresearch.loop")` |
| `run_experiment` missing evaluator re-enqueues loop | ✅ **Fixed** — explicit `send_task` on missing evaluator row and secret decryption failure |
| `apply_edit` worktree not cleaned up on git-apply failure | ✅ **Fixed** — `exp_path` stored and passed to `gitsvc.remove_worktree()` in `except GitError` |
| `decide._enqueue_loop` not called on merge failure | ✅ **Fixed** — `_enqueue_loop` called on all terminal paths |
| `db.py` missing WAL/PRAGMA settings | ✅ **Fixed** — WAL, foreign_keys, synchronous=NORMAL are in place |
| `score.py` first-iteration auto-rejects in `improvements_only` | ✅ **Fixed** — `score_before = score_after` on first iteration (delta=0), routed to human review |
| `on_chain_error` doesn't re-enqueue loop | 🔴 **Still broken** — docstring updated but code unchanged |
| `decide` uses `running` not `deciding` | 🔴 **Still open** — `enums.py` has no `deciding` value |
| `UniqueConstraint(session_id, iteration)` missing | 🔴 **Still open** |
| `secret_key` empty at startup | 🔴 **Still open** — `model_post_init` creates dirs but does not validate keys |
| SQLite `busy_timeout` missing | 🔴 **Still open** |
| `node_modules` in Git | 🔴 **Still open** |

***

## Priority Sequence for Day 9–10

The following five items should be addressed before the CLI validation gate. Items 1–3 block the gate; items 4–5 prevent the gate from being meaningless if it passes.

**1. Fix `on_chain_error` (one line)**
```python
# at end of on_chain_error, after db.close():
if session_id:
    try:
        celery_app.send_task("autoresearch.loop", args=[session_id])
    except Exception as e:
        logger.warning("on_chain_error: could not re-enqueue loop for %s: %s", session_id, e)
```
This is the highest-leverage single change. It converts every class of chain crash from a session-halting event to a recoverable one.

**2. Add `task_reject_on_worker_lost=True` to `celery_app.conf` (one line)**
```python
task_reject_on_worker_lost=True,
```
Without this, `--reload` on the API service and `restart: unless-stopped` on the worker mean every deploy or OOM event silently drops in-flight tasks.

**3. Add `PRAGMA busy_timeout=5000` to `db.py` (one line)**
```python
cur.execute("PRAGMA busy_timeout=5000")
```
This prevents `database is locked` errors that will surface under `--concurrency=2` during the Day 10 validation run.

**4. Add startup guard for empty API keys in `config.py`**
```python
@model_validator(mode="after")
def _check_keys(self) -> "Settings":
    if not self.secret_key:
        raise ValueError("AR_SECRET_KEY must be set")
    if self.llm_provider == "anthropic" and not self.anthropic_api_key:
        raise ValueError("AR_ANTHROPIC_API_KEY must be set when llm_provider=anthropic")
    if self.llm_provider == "openai" and not self.openai_api_key:
        raise ValueError("AR_OPENAI_API_KEY must be set when llm_provider=openai")
    return self
```

**5. Remove `docker.sock` from `api`, remove `--reload`, and drop Redis port from host**
- In `docker-compose.yml`: remove `- /var/run/docker.sock:/var/run/docker.sock` from the `api` service (keep on `worker`)
- Replace `--reload` with `--workers 1` (single uvicorn worker for SQLite compatibility)
- Remove `ports: - "16379:6379"` from `redis` (internal Docker network is sufficient)

**Phase 2 (before shipping real sessions):**
- Add `ExperimentStatus.deciding` to `enums.py` + migration
- Add `UniqueConstraint("session_id", "iteration")` to `experiment.py` + migration
- Add `Experiment.worktree_path` column + migration
- Add LLM retry/timeout decorators
- Remove `node_modules` and `dist` from Git tracking