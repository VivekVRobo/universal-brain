# ADR-0008: Rollback Engine Specification (A1 Reversibility Mechanics)

**Status:** Proposed (Pending Operator Review)  
**Date:** 2026-09-02  
**Authority:** Derived from Invariants ALN-007, ALN-016 and ADR-0002

---

## Context

Invariant `ALN-007` mandates that every A1 action must have a *"tested rollback."* However, declaring an action "reversible" without defining the underlying mechanics leads to broken undo routines, partial file writes, and silent data corruption. Furthermore, creating uncontrolled shadow Git branches across a 2-year lifecycle results in thousands of dangling refs, bloated repositories, and degraded Git performance.

## Decision

We implement a multi-domain **Deterministic Rollback Engine** using Copy-on-Write (CoW) overlays, Git shadow branches, container sandboxing, and database savepoints, governed by a strict **Lifecycle & Pruning Policy**:

### 1. File and Code Modifications
- **Shadow Branching:** Prior to any file write, the Kernel creates an isolated Git shadow branch or worktree (`shadow/{task_id}/{seq}`).
- **Preflight Rollback Test:** Before committing the edit to the working branch:
  1. The Kernel generates a unified reverse diff (`patch -R`).
  2. It executes a preflight dry run: `patch -R --dry-run` on a temporary file copy.
  3. If the dry-run test fails or encounters merge/patch conflicts, the action is **rejected immediately before execution**.
- **Execution & Rollback:** The edit is applied to the working branch. If a subsequent task failure occurs or rollback is commanded via `REVOKE_LEASE`, the Kernel executes `git reset --hard {pre_action_commit_hash}`.

### 2. Terminal and Environment Commands
- **Container Isolation:** Commands that install dependencies (`pip install`, `apt install`, `npm install`) or compile binaries are strictly executed inside ephemeral Docker containers or disposable virtual environments (`.venv`).
- **Rollback:** Rollback consists of discarding the container (`docker rm -f {container_id}`) or tearing down the virtual environment (`rm -rf {venv_path}`).
- **Escape Prevention:** Any command attempting to modify global host configuration outside the container/sandbox cannot be classified as A1; it is automatically escalated to **A2** requiring explicit operator confirmation.

### 3. Database Modifications
- **Transactional Savepoints:** Every database modification performed during a task is wrapped in an explicit SQL `SAVEPOINT {action_id}`.
- **Rollback:** Rollback executes `ROLLBACK TO SAVEPOINT {action_id}`.

### 4. Branch Lifecycle, Pruning & Squash Policy (Preventing Git Bloat)
To prevent the **"Git Branch Bloat Trap"** over extended projects:
- **Active Rollback Sliding Window:** The Kernel maintains a maximum of **10 active rollback checkpoints** per project.
- **Automated Squashing:** As new actions succeed and pass verification criteria, rollback points older than 10 are squashed into the main branch commit history. Intermediate shadow branches are pruned (`git branch -D`).
- **Patch Offloading to Cold Storage:** If detailed intermediate audit diffs are needed for long-term historical records, they are compressed as unified patch files (`patches_{task_id}.diff.gz`) and moved to Tier 3 cold storage (Google Drive / Telegram archive channel).
- **Scheduled Compaction:** A maintenance daemon executes `git gc --aggressive --prune=now` every Sunday at 03:00 UTC to compact loose objects and optimize repository packfiles.

### 5. Audit & Verification Trail
- Every executed rollback emits a tamper-evident audit event (`ALN-016`) capturing:
  `action_id`, `task_id`, `reason`, `pre_state_hash`, `post_state_hash`, and `verification_evidence_ref`.

## Consequences

- **Positive:** Eliminates "best-effort" or hallucinated rollbacks. Reversibility is mathematically tested before any disk write.
- **Positive:** Failed agent experiments leave zero residual debris on the host.
- **Positive:** Prevents repository bloat, ensuring Git operations remain instantaneous over years of autonomous execution.
- **Negative / Complexity:** Introduces slight preflight latency (50–150ms) to run `patch --dry-run` and Docker container instantiation.
