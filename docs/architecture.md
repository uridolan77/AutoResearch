# AutoResearch Platform v4 — Final Buildable Plan
## Generic Python Backend + React Frontend for Autonomous Iterative Improvement

***

## Status: Buildable

All review-mandated fixes from v2 and v3 are applied and locked. The six v3 corrections are resolved below before the spec begins.

| v3 Issue | Resolution |
|----------|-----------|
| `improvements_only` inverted wording | Corrected: auto-reject on `score_delta ≤ 0`; pause only on positive deltas |
| Hostname network allowlisting unimplemented | Phase 1: `--network none` / `--network bridge` (on/off). Phase 2: Squid DNS egress proxy on custom Docker network |
| Pause semantics implicit | Explicit: `loop` checks `session.status == paused` before re-enqueuing `plan`; `awaiting_review` experiments complete normally |
| `decide` not idempotent | Guarded with `WHERE status = 'awaiting_review'`; subsequent calls are no-ops (409) |
| Stale review clogs session | `review_timeout_hours` (default 48h); Celery Beat auto-rejects on expiry |
| Worktree disk growth | Prune worktrees older than N iterations back (default 10); journal + object store retained |
| Retry budget unspecified | Max 3 retries per iteration on validation failure; all charged to `tokens_used`; after 3 → mark `failed`, advance |
| WebSocket diff payload too large | `experiment.awaiting_review` sends `{id, delta, score_before, score_after}`; client fetches diff via REST |

***

## North-Star Metric

**Kept-experiments per dollar.** Captures agent quality, evaluator strictness, and cost efficiency in one signal. Everyone will try to optimise iteration count instead — don't let them.[^1][^2]

***

## Design Invariants (Final, Non-Negotiable)

1. `max_files_per_diff` enforced per session (default 1, hard ceiling 5). One logical change per iteration.[^3][^4]
2. Fixed wall-clock budget per experiment. All results directly comparable.[^5]
3. Human owns `program.md`; agent owns the target artifact; backend owns the loop. Agent never edits `program.md`.[^3]
4. Git-as-memory. Every experiment — kept, reverted, failed — is committed.[^6]
5. Human review is a state machine, not a blocking call.[^7]
6. Rejection comments are first-class context. Verbatim in next iteration's "Things not to try" block.[^8]
7. Evaluation is objective and grep-able. "Looks good" is banned.[^9]
8. Secrets never reach the proposer model. Runtime injection only.[^10]
9. Edit validation runs before the LLM call.[^1]
10. `decide` is idempotent. State transition guarded at DB level.
11. Stale reviews auto-reject. Sessions never block indefinitely.
12. Worktrees are pruned. Disk usage is bounded.

***

## Repository Structure

```
autoresearch-platform/
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routers (REST + WebSocket)
│   │   ├── core/                # Config, DB (SQLite), Redis, secrets
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── tasks/               # Celery task chains + Beat schedule
│   │   ├── evaluators/          # Registry, CommandEvaluator, PythonEvaluator, LLMJudgeEvaluator
│   │   ├── agent/               # LLM adapter, context builder, diff validator, deduplicator
│   │   ├── journal/             # SessionJournal (autoresearch.jsonl)
│   │   ├── git_service/         # Worktree management, pruning, commit, reset, merge
│   │   └── secrets/             # Encrypted store, context filter, runtime injector
│   ├── Dockerfile
│   ├── docker-compose.yml       # FastAPI + Celery worker + Celery Beat + Redis
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── pages/               # Home/Ingest, Sessions, SessionDetail, Review, Leaderboard
│   │   ├── components/          # DiffViewer, ExperimentTimeline, ScoreChart, ReviewBar
│   │   ├── hooks/               # useWebSocket, useSession, useExperiment
│   │   └── api/                 # openapi-fetch typed client
│   └── vite.config.ts
│
└── docs/
    ├── program-md-guide.md
    ├── evaluator-guide.md
    └── secrets-guide.md
```

***

## Domain Model (SQLite / SQLAlchemy)

### Session

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | PK |
| `name` | str | Human label |
| `folder_path` | str | Absolute local path or git clone URL |
| `target_file` | str | Relative path; agent-editable surface |
| `program_md` | text | Snapshot at session start |
| `evaluator_id` | FK | Registered evaluator |
| `wall_clock_budget_s` | int | Per-experiment hard cap |
| `token_cap_session` | int | Total session token budget |
| `token_cap_iter` | int | Per-iteration token budget |
| `max_files_per_diff` | int | Default 1, ceiling 5 |
| `review_mode` | enum | `always / improvements_only / auto_approve` |
| `review_timeout_hours` | int | Default 48; auto-reject on expiry |
| `worktree_prune_window` | int | Prune worktrees older than N iterations back; default 10 |
| `validation_retry_max` | int | Max retries per iteration on validation failure; default 3 |
| `status` | enum | `idle / running / paused / draining / stopped / complete` |
| `tokens_used` | int | Running total |
| `created_at` | datetime | |

### Experiment

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | PK |
| `session_id` | FK | |
| `iteration` | int | Sequential within session |
| `parent_commit` | str | Git SHA before edit |
| `experiment_commit` | str | Git SHA of applied edit |
| `branch_ref` | str | Worktree branch |
| `status` | enum | `pending / running / scored / awaiting_review / kept / reverted / failed / duplicate` |
| `diff_text` | text | Unified diff |
| `diff_hash` | str | SHA256 of normalised diff |
| `validation_attempts` | int | Retries on validation failure (max 3) |
| `score_before` | float | |
| `score_after` | float | |
| `score_delta` | float | |
| `tokens_used` | int | |
| `decision` | enum | `null / approved / rejected / auto_rejected_timeout / auto_rejected_no_improvement` |
| `rejection_comment` | str | ≤ 500 chars; fed into next-iteration context |
| `kept` | bool | |
| `worktree_pruned` | bool | Whether checkout has been removed |
| `created_at` | datetime | |

### Run, Evaluator, Secret

Same structure as v3. `Evaluator` gains:

| Field | Type | Notes |
|-------|------|-------|
| `network_mode` | enum | `none / bridge` (Phase 1); `egress_proxy` (Phase 2) |
| `network_allow` | JSON | Hostname list — validated in Phase 2 only |

***

## Task Chain — State Machine (Complete, Final)

```
Session starts
    │
    ▼
[loop checks session.status]
    ├── paused → do not re-enqueue; stop here
    ├── draining / stopped / complete → do not re-enqueue
    └── running → continue
    │
    ▼
autoresearch.plan
    ├── Check token_cap_iter and token_cap_session; if exhausted → trigger drain
    ├── Build context: program.md + target file + journal summary + "Things not to try" block
    └── Call proposer (Claude Sonnet 4.5); get diff
    │
    ▼
autoresearch.apply_edit                     [Validation runs pre-LLM-cost is already done;
    ├── Validate file count ≤ max_files_per_diff    validation here is pre-evaluator-cost]
    ├── Validate all files on whitelist
    ├── Validate no protected files touched (.env, program.md, etc.)
    ├── Validate diff non-empty
    ├── Check diff_hash against session history → if duplicate: mark duplicate, re-enqueue plan
    │
    ├── VALIDATION FAILURE:
    │     validation_attempts < max (3) → retry: re-call plan with "validation failed: reason" in context
    │     validation_attempts == max → mark failed, advance to next iteration
    │
    └── VALIDATION PASS: apply diff to worktree, commit
    │
    ▼
autoresearch.run_experiment
    └── Spawn Docker sandbox (network: none or bridge per evaluator.network_mode)
        Inject secrets as --env flags (decrypted at runtime; never logged)
        Enforce wall_clock_budget_s via container timeout
    │
    ▼
autoresearch.score
    ├── Parse metric_payload, compute score_delta
    ├── Apply review_mode:
    │     auto_approve      → set decision=approved, enqueue decide directly
    │     improvements_only → score_delta ≤ 0: set decision=auto_rejected_no_improvement, enqueue decide
    │                         score_delta > 0: set status=awaiting_review, emit WS event, CHAIN TERMINATES
    │     always            → set status=awaiting_review, emit WS event, CHAIN TERMINATES
    └── Append journal record (partial — decision TBD for awaiting_review)
    │
    ╔══ Human Review (for awaiting_review only) ═══════════════╗
    ║  POST /experiments/{id}/review                           ║
    ║  Guards: WHERE status = 'awaiting_review'                ║
    ║  Duplicate call → 409 no-op                              ║
    ║  Writes: decision, rejection_comment                     ║
    ║  Enqueues: autoresearch.decide as fresh task             ║
    ╚══════════════════════════════════════════════════════════╝
    │
    ╔══ Stale Review (Celery Beat, runs every hour) ════════════╗
    ║  SELECT experiments WHERE status = 'awaiting_review'     ║
    ║    AND created_at < NOW() - review_timeout_hours         ║
    ║  Sets decision = auto_rejected_timeout                   ║
    ║  Enqueues autoresearch.decide for each                   ║
    ╚══════════════════════════════════════════════════════════╝
    │
    ▼
autoresearch.decide                              [Idempotent]
    ├── Guard: experiment.status must be 'awaiting_review' (DB-level check)
    │   If not → no-op, return
    ├── On approve:   git commit keep; set status=kept, kept=True
    ├── On reject:    git reset --hard; set status=reverted, kept=False
    ├── Append final journal record (outcome + rejection_comment)
    ├── Check worktree prune policy: if experiment.iteration < (current - prune_window) → prune worktree
    ├── Check token budget: if tokens_used ≥ token_cap_session → session.status = draining
    └── Re-enqueue autoresearch.loop (or stop if draining/paused/stopped)
    │
    ▼
autoresearch.loop → back to top
```

***

## Pause Semantics (Explicit)

**Pausing** sets `session.status = paused`. The `loop` task checks this flag before re-enqueuing `plan`:

```python
# autoresearch/tasks/loop.py
@celery.task
def loop(session_id: str):
    session = db.get(Session, session_id)
    if session.status in ('paused', 'draining', 'stopped', 'complete'):
        return  # Do not re-enqueue plan
    chain(plan.s(session_id), ...).delay()
```

Experiments already in `awaiting_review` when pause is triggered **continue to completion** via the review endpoint — pause blocks the *next* iteration from starting, not the current one in-flight. This is intentional and must be documented in the API.

**Resuming** sets `session.status = running` and enqueues `loop` directly.

***

## `decide` Idempotency

```python
# autoresearch/tasks/decide.py
@celery.task
def decide(experiment_id: str):
    with db.begin():
        exp = db.execute(
            select(Experiment)
            .where(Experiment.id == experiment_id)
            .where(Experiment.status == 'awaiting_review')
            .with_for_update()
        ).scalar_one_or_none()

        if exp is None:
            return  # Already decided — idempotent no-op

        # Apply decision...
```

`POST /experiments/{id}/review` returns 409 if `experiment.status != 'awaiting_review'`.

***

## Worktree Pruning

Pruning happens at the end of every `decide` call:

```python
# Prune worktrees of experiments older than prune_window iterations
prune_threshold = current_iteration - session.worktree_prune_window
stale = db.query(Experiment).filter(
    Experiment.session_id == session_id,
    Experiment.iteration < prune_threshold,
    Experiment.worktree_pruned == False,
    Experiment.status.in_(['kept', 'reverted', 'failed'])
).all()

for exp in stale:
    git_service.remove_worktree(exp.branch_ref)
    exp.worktree_pruned = True
    # journal record and git object store are retained
```

Default window of 10 keeps the last 10 iterations' worktrees available for inspection. `autoresearch.jsonl` and the git object store are never pruned — only the filesystem checkout is removed.[^6]

***

## Validation Retry Logic

```python
# In autoresearch.apply_edit
for attempt in range(1, session.validation_retry_max + 1):
    diff = propose_diff(context, retry_hint=last_failure_reason)
    result = validate(diff, session)

    if result.ok:
        apply_and_commit(diff)
        break

    last_failure_reason = result.reason
    experiment.validation_attempts = attempt
    experiment.tokens_used += result.tokens_spent  # Retries charged to budget

    if attempt == session.validation_retry_max:
        mark_failed(experiment, reason=f"validation failed after {attempt} retries: {last_failure_reason}")
        enqueue_loop(session_id)  # Advance to next iteration
        return
```

All retries are charged to `tokens_used`. The retry hint ("validation failed: diff touches 3 files, max is 1") is passed back to the proposer to guide the next attempt.

***

## Review Mode Semantics (Corrected)

| Mode | Behaviour |
|------|-----------|
| `always` | Every experiment pauses at `awaiting_review` for human approval |
| `improvements_only` | `score_delta ≤ 0` → auto-reject (`decision = auto_rejected_no_improvement`), no human needed; `score_delta > 0` → pause for human review |
| `auto_approve` | All experiments auto-approved; `decide` enqueued directly from `score`; fully autonomous |

`improvements_only` auto-reject means the revert happens via `decide` in the normal way — the auto-approval decision feeds `decide`, which calls `git reset --hard`. No new code path.[^8]

***

## Network Policy (Phase 1 / Phase 2)

### Phase 1 — On/Off Only

```python
# evaluator.network_mode: 'none' | 'bridge'
docker_flags = '--network none' if evaluator.network_mode == 'none' else '--network bridge'
```

| Evaluator type | Default `network_mode` |
|----------------|----------------------|
| `CommandEvaluator` | `none` |
| `LLMJudgeEvaluator` | `bridge` |
| `PythonEvaluator` | `none` |

Hostname-level filtering is **not implemented in Phase 1**. If a `CommandEvaluator` needs PyPI, set `network_mode = bridge` and accept unrestricted outbound for that evaluator.

### Phase 2 — DNS Egress Proxy

Deploy Squid as a sidecar container on a custom Docker network (`ar_eval_net`). Evaluator containers join `ar_eval_net` instead of `bridge`. Squid enforces an allowlist from `evaluator.network_allow`. Unknown hostnames → 403.

```yaml
# docker-compose.yml (Phase 2 addition)
squid:
  image: ubuntu/squid
  volumes:
    - ./squid.conf:/etc/squid/squid.conf:ro
  networks:
    - ar_eval_net
```

Phase 2 cost: ~1 day of work. Phase 1 cost: zero. This is the right split.[^10]

***

## Secrets Handling (Three Layers)

### Layer 1 — Context Filter

```python
DENY_PATTERNS = [
    '.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx',
    'secrets/', 'credentials.json', 'token.json', '.netrc',
    '*.secret', 'id_rsa', 'id_ed25519', '.aws/credentials'
]
```

Files matching any pattern or present in `.gitignore` are replaced with `[REDACTED: secret file]` in agent context. The agent never sees their names or contents.

### Layer 2 — Encrypted Store

AES-256-GCM in SQLite. App key from `AR_SECRET_KEY` env var. CLI:

```bash
ar secrets add OPENAI_API_KEY sk-...
ar secrets remove OPENAI_API_KEY
ar secrets list   # Names only, never values
```

### Layer 3 — Runtime Injection

```python
# In run_experiment task — decrypted at container spawn, never logged
secrets = {name: decrypt(ciphertext) for name, ciphertext in
           get_secrets(evaluator.secret_refs)}

docker.run(
    image=evaluator_image,
    volumes={worktree_path: {'bind': '/workspace', 'mode': 'rw'}},
    environment={**secrets, **base_env},
    network_mode=evaluator.network_mode,
    ...
)
```

Secrets are never written to disk, never appear in logs, never passed to proposer or judge models.

***

## Rejection Feedback in Context

```
[program.md contents]

[target file contents]

[Journal — last 10 experiments]
  iter 12: KEPT        Δ+3.2  "tightened FIP cross-reference"
  iter 13: REVERTED    Δ-0.8  (no comment)
  iter 14: REJECTED    Δ+1.1  "weakened Firewall tier-typing; do not collapse W/K into kcal"
  iter 15: REJECTED    Δ+0.4  "anchor case citation dropped; every claim needs an exhibited case"
  iter 16: DUPLICATE          (hash match — skipped)

[Things not to try — last 5 rejection comments]
  • "weakened Firewall tier-typing; do not collapse W/K into kcal"
  • "anchor case citation dropped; every claim needs an exhibited case"
```

Capped at 5 × 500 chars = 2,500 tokens maximum. `rejection_comment` stored on the `Experiment` record and appended to `autoresearch.jsonl`.[^6]

***

## Diff Deduplication

```python
import hashlib, re

def normalise_diff(diff_text: str) -> str:
    lines = [l for l in diff_text.splitlines()
             if not l.startswith('@@') and not l.startswith('---') and not l.startswith('+++')]
    return re.sub(r'\s+', ' ', ' '.join(lines)).strip()

def diff_hash(diff_text: str) -> str:
    return hashlib.sha256(normalise_diff(diff_text).encode()).hexdigest()
```

SHA256 of normalised diff (hunk headers, file headers, whitespace stripped). Catches cosmetic variations and literal duplicates. If hash matches any prior experiment in the session → mark `duplicate`, skip eval budget, add "duplicate detected" to next-iteration context, advance immediately.[^8]

Phase 2 upgrade: AST-level semantic hash for Python/JS (do not implement in Phase 1 even if tempted).

***

## WebSocket Events (Final)

| Event | Payload | Notes |
|-------|---------|-------|
| `experiment.started` | `{id, iteration}` | `apply_edit` begins |
| `experiment.running` | `{id, elapsed_s}` | Heartbeat from `run_experiment` |
| `experiment.duplicate` | `{id, matched_hash}` | Dedup fired |
| `experiment.scored` | `{id, score_before, score_after, delta}` | `score` completes |
| `experiment.awaiting_review` | `{id, delta, score_before, score_after}` | Diff fetched separately via REST |
| `experiment.kept` | `{id, commit_sha}` | `decide` approves |
| `experiment.reverted` | `{id, decision, reason}` | `decide` reverts (reject / auto-reject) |
| `experiment.failed` | `{id, reason}` | Validation or evaluator failure |
| `session.paused` | `{id}` | Pause confirmed |
| `session.token_warning` | `{pct_used}` | 80% of `token_cap_session` |
| `session.stopped` | `{reason}` | Budget exhausted / explicit stop |

***

## API Surface (Complete)

```
# Folder ingestion
POST   /folders/ingest                  Register folder (local path or git clone URL)
GET    /folders/{id}/targets            Suggest editable target files + evaluator type

# Sessions
POST   /sessions                        Create session
GET    /sessions                        List sessions (filter by status)
GET    /sessions/{id}                   Detail + live stats (tokens_used, kept_rate, kept_per_dollar)
POST   /sessions/{id}/start             Enqueue first loop task
POST   /sessions/{id}/pause             Set status=paused (takes effect after current experiment)
POST   /sessions/{id}/resume            Set status=running, enqueue loop
POST   /sessions/{id}/stop              Set status=stopped
PATCH  /sessions/{id}/program           Edit program.md (takes effect next iteration)

# Experiments
GET    /sessions/{id}/experiments       Leaderboard (filter: status, kept, delta_min/max, date)
GET    /experiments/{id}               Detail: diff_text, score, run logs, rejection history
POST   /experiments/{id}/review         Submit decision {decision, comment ≤500 chars}
                                        → 409 if status != awaiting_review (idempotency guard)
                                        → enqueues decide as fresh task
POST   /experiments/{id}/skip           Force-reject without comment (manual stale-review resolution)

# Evaluators
GET    /evaluators                      List
POST   /evaluators                      Register
GET    /evaluators/{id}                 Detail
DELETE /evaluators/{id}                 Remove if no active sessions

# Secrets
POST   /secrets                         Register encrypted secret {name, value}
DELETE /secrets/{name}                  Remove
GET    /secrets                         List names only (values never returned)

# Dry-run / cost estimation
POST   /sessions/estimate               {program_md, evaluator_id, iterations} → estimated token cost

# Regroup (Phase 2)
POST   /sessions/{id}/regroup           Propose independent changesets from kept experiments

# WebSocket
WS     /ws/sessions/{id}                Real-time event stream
```

***

## Frontend Architecture

### Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 19 + TypeScript + Vite |
| State | Zustand (UI) + TanStack Query (server) |
| Real-time | Native WebSocket hook |
| Diff viewer | `react-diff-viewer-continued` — actively maintained, MIT[^11] |
| Charts | Recharts |
| Styling | Tailwind CSS |
| API client | `openapi-fetch` (typed from FastAPI OpenAPI schema) |

### Pages

**`/` — Folder Ingestion**
Path input (not drag-drop) or git clone URL. Auto-detects target file + evaluator type. Cost estimator widget (calls `/sessions/estimate`). One-click session creation.

**`/sessions` — Sessions List**
Status badges, current score, kept-rate, token spend, kept-per-dollar, time since last activity.

**`/sessions/:id` — Session Detail (Live)**
Real-time experiment timeline (dots, colored by status). Score progression chart. Current experiment card. Inline `program.md` editor. Pause/resume/stop controls. Token budget progress bar with 80% warning.

**`/sessions/:id/experiments/:expId` — Experiment Review**
`react-diff-viewer-continued` split/unified toggle.[^11]
Score before/after delta badge. Evaluator stdout accordion. Rejection history for this session. **Approve** / **Reject** + comment (500-char, enforced). Keyboard: `a` = approve, `r` = reject, `e` = focus comment. `skip` button for manual stale-review resolution.

**`/sessions/:id/leaderboard`**
Kept experiments ranked by score delta. Filterable. "Ship" → regroup flow (Phase 2).

**`/evaluators`** — Registry, create, inline test against a folder.

**`/secrets`** — Register/delete. Values write-only.

***

## Phased Build Plan

### Phase 1 — 16 Days (CLI-First, Then React)

#### Days 1–3: Foundation
- Repo scaffold, Docker Compose (FastAPI + Celery worker + Celery Beat + Redis; SQLite on volume)
- SQLAlchemy models + Alembic migrations (all fields above including `worktree_pruned`, `validation_attempts`)
- `GitService`: worktree-per-experiment, commit, reset-hard, merge, prune[^12][^13]
- LLM adapter (Claude Sonnet 4.5 + GPT-4o-mini), per-call token counting[^14][^1]
- Secret store: AES-256-GCM, CLI `ar secrets add/remove/list`

#### Days 4–6: The Chain
- `plan` task: context builder with "Things not to try" block, pre-call token cap check
- `apply_edit` task: full validation pipeline + retry logic (max 3) + dedup hash check
- `run_experiment` task: Docker `--network none/bridge`, worktree mount, secret injection, wall-clock cap[^10]
- `score` task: metric parsing, delta computation, review_mode routing, chain termination or direct decide enqueue

#### Days 7–8: Review Gate + Decide + Beat
- `decide` task: idempotent state transition, git keep/revert, journal append, worktree prune call, token budget check, drain policy, loop re-enqueue
- `POST /experiments/{id}/review` (409 guard, enqueues decide)
- Celery Beat stale-review task (hourly scan, auto-rejects on timeout)[^7]
- `loop` task: pause/drain/stop checks before re-enqueue

#### Days 9–10: Evaluators + Folder Ingestion + Cost Controls
- `CommandEvaluator` + `LLMJudgeEvaluator` with `--network none/bridge`[^9]
- Dry-run cost estimator endpoint
- Folder ingestion: local path + git clone URL, target-file heuristics, starter `program.md` templates[^15]
- All session lifecycle API endpoints

#### ✅ CLI Validation Gate — End of Day 10
Run the loop on a toy Python project (`CommandEvaluator` measuring pytest coverage). Confirm:
- Loop ratchets (kept-rate > 0%)
- Rejection feedback reduces near-duplicate proposals
- Dedup hash fires on re-submission
- `improvements_only` auto-rejects non-positive deltas correctly (not inverted)
- Drain policy terminates cleanly at token cap
- Stale-review Beat task fires and advances the session
- Worktree prune removes old checkouts; object store intact
- Journal survives a forced worker restart
- `decide` is no-op on double-call

**Do not write React until all of these pass.**

#### Days 11–13: React Frontend (MVP Subset)
- Session creation page (path input + git URL + cost estimator)
- Live session detail: WebSocket timeline + score chart + token counter
- Experiment review: `react-diff-viewer-continued` + Approve/Reject + comment + keyboard shortcuts[^11]
- Sessions list with status badges

#### Days 14–16: First Real Session + Buffer
- TTU §7.7.6 validation: 50 iterations, $15 token cap, `LLMJudgeEvaluator` with six-axis rubric
- Day 15–16: buffer for issues found during validation
- `CommandEvaluator` nanochat demo to validate non-prose path[^3]

**Phase 1 exit criterion**: human reviewer clicks Approve on an autonomously produced §7.7.6 diff in under 30 seconds via the UI. Not "interesting" — approvable as-is.

***

### Phase 2 — Beta (Weeks 5–8)

- `PythonEvaluator` with `evaluate(worktree_path) -> float`
- S3/MinIO ArtifactStore for logs, diffs, evaluator outputs (gitignored)
- Squid DNS egress proxy on custom Docker network (`ar_eval_net`); `evaluator.network_allow` enforced
- AST-level diff deduplication for Python/JS
- Regroup flow: independent changesets from kept experiments, Kanban review before merge[^16][^6]
- Prometheus metrics (experiments/hour, kept-rate, kept-per-dollar, revert reasons)[^2]
- Inline diff comments in review UI[^11]
- Leaderboard + "Ship" button

**Phase 2 exit criterion**: 10 real sessions across 2+ evaluator types, kept-per-dollar trending up.

***

### Phase 3 — GA (Weeks 9+)

- SQLite → Postgres; multi-user auth + session ownership
- Async parallel experiments: N workers per session[^17]
- GitHub/GitLab: auto-open PR from kept session branch
- Domain `program.md` template library: ML training, prompt optimisation, bundle shrinkage, prose revision, test-pass-rate improvement
- Journal replay tool: reconstruct any session from `autoresearch.jsonl` independent of DB[^6]
- Plugin SDK: third-party evaluator registration with schema + network policy validation

**Phase 3 exit criterion**: second human user runs a session end-to-end without engineering assistance and ships regrouped branches to main.

***

## Deliberate Omissions

| Omitted | Reason |
|---------|--------|
| Blocking Celery review task | Antipattern — state machine instead[^7] |
| Hostname-level network filtering in Phase 1 | Unaccounted implementation cost; on/off only; Squid in Phase 2 |
| Drag-and-drop folder ingestion | Browsers cannot read arbitrary local paths |
| Regroup UI in Phase 1 | Needs 10+ sessions of real data first[^6] |
| Async parallelism in Phase 1–2 | LLM spend bottlenecks before wall-clock[^17] |
| Agent-editable `program.md` | Ever[^4] |
| AST-level diff dedup in Phase 1 | SHA256 normalised hash covers the real failure mode |
| Postgres in Phase 1–2 | SQLite satisfies transactional integrity with zero extra infra |
| GitHub API in experiment hot path | Latency + availability dependency[^12] |
| Semantic/embedding diff similarity | Overkill for MVP; hash covers the daily failure mode |

***

## The One Test That Matters

By end of Phase 1 Day 14, a human reviewer — reading a diff of §7.7.6 produced autonomously — must click **Approve** without editing the result. Not "interesting". Not "directionally correct". Approvable as-is. If the loop clears that bar on philosophical prose under a six-axis rubric, it will clear every subsequent bar on easier domains.[^15][^2][^17]

---

## References

1. [Karpathy's autoresearch Is a Skill: How a 42,000-Star Repo Became ...](https://thelgtm.dev/karpathys-autoresearch-is-a-skill-how-a-42-000-star-repo-became-a-claude-code-loop-for-any-codebase/) - On March 7, 2026, Andrej Karpathy pushed a repo to GitHub with a README that opens like this: One da...

2. [Autoresearch: The Loop That Improves Your Work While You Sleep](https://thecreatorsai.com/p/autoresearch-the-loop-that-improves) - Autoresearch by Andrej Karpathy: how the AI loop that runs 100 experiments overnight works, real bus...

3. [karpathy/autoresearch: AI agents running research on ... - GitHub](https://github.com/karpathy/autoresearch) - Contains the full GPT model, optimizer (Muon + AdamW), and training loop. Everything is fair game: a...

4. [I Turned Karpathy's Autoresearch Into a Skill That Optimizes Anything](https://dev.to/alireza_rezvani/i-turned-karpathys-autoresearch-into-a-skill-that-optimizes-anything-here-is-the-architecture-57j8) - Karpathy released autoresearch last week. 31,000 stars. 100 ML experiments overnight on one GPU. Eve...

5. [GitHub - karpathy/autoresearch: AI agents automatically conducting ...](https://ht-x.com/posts/2026/03/github-karpathy-autoresearch-ai-agents-running-res/) - The operation of autoresearch is simple but powerful. The AI agent modifies the train.py file, which...

6. [GitHub - davebcn87/pi-autoresearch: Autonomous experiment loop ...](https://github.com/davebcn87/pi-autoresearch) - Autonomous experiment loop extension for pi. Contribute to davebcn87/pi-autoresearch development by ...

7. [Human-in-the-loop | OpenAI Agents SDK - GitHub Pages](https://openai.github.io/openai-agents-js/guides/human-in-the-loop/) - This guide covers the SDK's approval-based human-in-the-loop flow. When a tool call requires approva...

8. [Self-Improving Coding Agents - Addy Osmani](https://addyosmani.com/blog/self-improving-agents/) - You can even automate a diff review - e.g., abort the loop if the diff is much larger than expected ...

9. [Autoresearch Agent — Agent Skill | PromptCreek](https://www.promptcreek.com/skills/autoresearch-agent) - Autonomous experiment loop that optimizes any file by a measurable metric.

10. [Git Worktrees Need Runtime Isolation for Parallel AI Agent ...](https://www.penligent.ai/hackinglabs/git-worktrees-need-runtime-isolation-for-parallel-ai-agent-development/) - Git worktrees isolate branches, not runtimes. This article breaks down port collisions, Docker Compo...

11. [praneshr/react-diff-viewer: A simple and beautiful text diff ... - GitHub](https://github.com/praneshr/react-diff-viewer) - A simple and beautiful text diff viewer component made with Diff and React. - praneshr/react-diff-vi...

12. [Git Worktree Isolation Patterns for Parallel AI Agent Development](https://zylos.ai/research/2026-02-22-git-worktree-parallel-ai-development) - How git worktrees enable multiple AI coding agents to work on the same codebase simultaneously witho...

13. [Git Worktrees: Unlocking Git's Hidden Potential - Tutorials Dojo](https://tutorialsdojo.com/git-worktrees-unlocking-git-hidden-potential/) - Docker containers provide stronger isolation, but break the connection to the local repository. The ...

14. [README.md - karpathy/autoresearch - GitHub](https://github.com/karpathy/autoresearch/blob/master/README.md) - AI agents running research on single-GPU nanochat training automatically - karpathy/autoresearch

15. [Autoresearch Became a Primitive - Emergent Minds | paddo.dev](https://paddo.dev/blog/autoresearch-ecosystem/) - A traditional CI loop runs the same code with different inputs. An autoresearch loop changes the cod...

16. [Does Git worktree / Docker isolation actually speed up development ...](https://www.reddit.com/r/ClaudeCode/comments/1nkxswl/does_git_worktree_docker_isolation_actually_speed/) - Best practices for using Git worktree. Using Docker for parallel development tasks. Innovative uses ...

17. ['The Karpathy Loop': 700 experiments, 2 days, and a glimpse of ...](https://fortune.com/2026/03/17/andrej-karpathy-loop-autonomous-ai-agents-future/) - The former OpenAI and Tesla AI researcher's 'autoresearch' technique could be used by AI labs to spe...

