# Universal Brain V5.3 — Real-Environment Validation & Endurance

**Status:** Validation harness implemented; target-machine execution pending  
**Scope:** REQ-ENG-034 through REQ-ENG-040  
**Parent:** V5.2 Engineering Runtime Hardening

## Objective

V5.3 does not add another cognitive or provider layer. It turns V5.2's explicit target-machine proof gap into executable, resumable, tamper-evident validation.

The deployment rule is:

> A capability is not considered target-proven until the actual configured runtime executes the applicable check and produces verifiable evidence.

## Validation Session

`V53ValidationCheckpointStore` persists a session ID, workspace fingerprint, completed scenario IDs, scenario results, and a SHA-256 self-digest using atomic replacement.

If source files change unexpectedly between stages, resume fails closed. `.brain`, build caches, virtual environments, and other generated trees are excluded from the canonical workspace fingerprint so evidence writing itself does not create false drift.

## Local Ollama Proof

`V53OllamaValidator` contacts the operator-selected Ollama endpoint, lists installed models, verifies every requested model exists, performs a tiny health generation, and records:

- model identity;
- latency;
- response SHA-256 and byte count;
- selected Ollama runtime counters when available.

Raw model responses are not placed in the target report.

`V53OllamaPressureScenario` is a separate opt-in scenario. It sends one small concurrent request per selected model and can expose real RAM/VRAM scheduling/oversubscription behavior. It is never automatically enabled.

## Git / Merge-Conflict Lab

`V53DisposableGitLab` creates a temporary Git repository under the validation area, creates two independent worktrees, commits conflicting changes, verifies Git reports the unresolved file, aborts the merge, and verifies the base checkout is clean afterward. Successful labs are removed.

This proves the target Git/worktree/conflict primitives. Real production merge-coordinator evidence still comes from actual Engineering Agency mission runs.

## Authority-Gated Service Workload

`V53AuthorityServiceScenario` starts a bounded Python service through `ToolGateway` and `ManagedServiceProcessTool`, then checks status and logs through fresh capability tokens. The child prints a readiness marker and is stopped in `finally`. The EventStore hash chain must verify.

## Restart Recovery

`V53RestartRecoveryLab` deliberately uses two independent Python processes. The first creates a sealed validation checkpoint and exits with a known non-zero code. The second loads and verifies the same checkpoint and session ID. This proves evidence/checkpoint persistence across an actual process boundary rather than merely re-instantiating a class in one process.

## WSL2 ToolGateway Execution

When the operator supplies both a WSL distro and the Linux path mapping of the Windows checkout, `V53WSLIsolationExecutionScenario` builds a bounded WSL2 plan and passes only its opaque one-time plan ID across ToolGateway. The inner command prints a fixed marker.

The check can fail on a real machine if `systemd-run`, `unshare`, cgroup properties, user permissions, or network namespace policy are not actually usable. Such failure is evidence and must not be converted into success.

The harness does not install/configure WSL2, use `sudo`, or bypass credentials.

## Evidence Manifest

`V53EvidenceBundler` hashes each evidence artifact using SHA-256 and writes `v53-evidence-manifest.json`. Offline verification checks:

- manifest self-digest;
- artifact confinement to the evidence root;
- artifact existence;
- exact size;
- artifact SHA-256.

## Endurance

`scripts/v53_endurance.py` runs an explicit shell-free mission argv repeatedly through `EngineeringEnduranceHarness`, stores per-cycle stdout/stderr hashes and metadata, and seals the V5.3 evidence directory.

A duration under two hours is only a smoke run. Production/endurance claims require a real target-machine run lasting at least two hours with no unresolved applicable failures.

## Target Proof Matrix

| Capability | Cross-platform code proof | Target-machine proof required |
|---|---:|---:|
| V5.3 checkpoint/manifest integrity | Yes | final bundle verification |
| Disposable Git worktrees/conflict abort | Yes | recommended on Windows target |
| ToolGateway service lifecycle | Yes | required on target |
| Three configured Ollama models | Mock/unit only | required |
| Concurrent Ollama pressure | Mock/unit only | opt-in target evidence |
| Real stdio LSP | subprocess fixture | required production LSP |
| Tree-sitter native runtime | optional CI | required if used in deployment |
| WSL2 one-time isolation execution | code/unit | required on Windows |
| Hyper-V production execution | code/unit/host prerequisite probe | required if deployment uses Hyper-V |
| Restart recovery | cross-process code proof | required on target mission |
| >=2 hour mission | no | required |

## Non-Claims

V5.3 validation-harness code is not itself evidence that the user's Windows machine passed WSL2, Hyper-V, Ollama concurrency, or multi-hour endurance. Those labels remain pending until the target-generated evidence bundle exists and verifies.
