# Intelligence Fabric V4 Verification Record

**Checkpoint:** Adaptive Cognitive Control / Intelligence Fabric V4  
**Date:** 2026-09-07  
**Scope:** Adaptive capability discovery, evaluation-driven routing, memory-aware context retrieval, Council disagreement adjudication and synthesis, provider-session recovery, authorized browser/desktop transport boundaries, cognitive TaskDAG execution, Executive compatibility, control-plane/API security regression, and clean release packaging.

## Checkpoint statement

V4 is a **verified architectural/runtime checkpoint**, not a claim that every external frontier-model account, browser UI, desktop application, or production Verification Engine has been live-smoke-tested. External model routes remain disabled or operator-configured until their account, pricing, retention, quota, selector, and authorization assumptions are verified in the target environment.

The deterministic Kernel remains authoritative. Model output, Council consensus, adjudication, browser responses, and desktop-app responses remain cognition or tool proposals; they do not gain ToolGateway authority by being produced by a stronger model or by multiple models agreeing.

## Requirement / invariant coverage

This checkpoint is primarily traceable to:

- **REQ-IF-V4-001** — local capability evidence may refine routing without granting model authority;
- **REQ-IF-V4-002** — tested models do not self-grade routing evaluations;
- **REQ-IF-V4-003** — canonical/derived memory retrieval preserves provenance and epistemic state;
- **REQ-IF-V4-004** — Council disagreements remain explicit and adjudication is advisory;
- **REQ-IF-V4-005** — provider-session continuity is recoverable but non-canonical;
- **REQ-IF-V4-006** — browser uploads are bounded and interactive transports do not bypass authentication/security controls;
- **REQ-IF-V4-007** — Windows UI Automation is an optional authorized desktop transport;
- **REQ-IF-V4-008** — TaskDAG cognition cannot mark completion without an external verification adapter;
- **REQ-IF-V4-009** — required A2 Council independence fails closed when unavailable;
- **ALN-001** — executable work retains requirement traceability;
- **ALN-008/009** — models cannot expand action authority or permissions;
- **ALN-010** — completion requires acceptance/verification criteria;
- **ALN-011** — model agreement is not independent evidence;
- **ALN-012** — canonical continuity is independent of provider conversations;
- **ALN-013** — cloud/interactive context is minimized and cannot contain unrestricted local secrets by default;
- **ALN-014/020** — loss of critical controls or required verification fails state-changing work closed;
- **ALN-021** — memory/context provenance and conflict state are preserved.

## V4 adaptive-control verification

### Combined Intelligence Fabric + Executive + integration gate

Executed:

```text
python -m pytest -q \
  tests/unit/test_intelligence_fabric.py \
  tests/unit/test_intelligence_fabric_v3.py \
  tests/unit/test_intelligence_fabric_v4.py \
  tests/unit/test_executive_cognitive.py \
  tests/integration/test_m3_m4_master_gate.py \
  tests/integration/test_cellular_monolith.py
```

Result: **45 passed, 0 failed**.

This includes the **10 dedicated V4 adaptive cognitive-control tests** covering capability-evidence routing, provenance-aware context retrieval, provider-session recovery, Windows UIA driver registration, Council disagreement adjudication, and verifier-gated TaskDAG execution.

### API + security regression gate

Executed:

```text
python -m pytest -q \
  tests/unit/test_api_adversarial.py \
  tests/security/test_s1_authority_regression.py
```

Result: **18 passed, 0 failed**.

The lazy persistence boundary from V3 remains covered: importing/constructing the control plane does not eagerly instantiate the default database backend, while operations that actually require durable persistence still fail explicitly when the configured backend is unavailable.

### Python compilation

Executed:

```text
python -m compileall -q src tests
```

Result: **PASS**.

### Operator Console TypeScript

Executed:

```text
cd console
./node_modules/.bin/tsc --noEmit
```

Result: **PASS**.

### Intelligence catalog schema/configuration load

Executed by loading `config/intelligence_catalog.example.json` through `universal_brain.intelligence.load_catalog`.

Result: **PASS**.

The example routes remain disabled by default and contain only environment-variable references / operator configuration placeholders rather than raw credentials.

## Environment-limited checks — explicitly not claimed as passing

### Complete repository test collection

Executed:

```text
python -m pytest -q
```

Current sandbox result: **collection blocked** because `pgvector` is not installed:

```text
ModuleNotFoundError: No module named 'pgvector'
```

`pgvector>=0.2.5` remains a declared project dependency. This checkpoint does not convert that environment limitation into a passing result.

After excluding only `tests/unit/test_db_models.py`, the next persistence-heavy gate reaches the declared development dependency `aiosqlite` and is blocked in this sandbox because that package is also not installed:

```text
ModuleNotFoundError: No module named 'aiosqlite'
```

`aiosqlite>=0.20.0` is declared in the `dev` optional dependencies for a clean development install.

### Full Vite production bundle

Executed:

```text
cd console
npm run build
```

TypeScript completes, but Vite/Rollup is blocked by the copied cross-platform dependency tree in this Linux sandbox:

```text
Cannot find module @rollup/rollup-linux-x64-gnu
```

The clean release package intentionally excludes `node_modules`. A fresh `npm ci` on the target machine is required to install the correct platform-specific optional Rollup binary before production bundling.

### Live external-provider/browser/desktop execution

**Not executed and not claimed.** Production smoke testing still requires explicit operator authorization and a target environment containing the relevant accounts/applications. In particular, this checkpoint does not claim:

- live paid/frontier API invocation;
- live ChatGPT/Claude/Gemini/Grok browser selectors;
- provider login/MFA/CAPTCHA automation;
- live Windows AI-application UIA selectors from this Linux sandbox;
- production ToolGateway execution of model-proposed tools;
- a production `MissionVerificationAdapter` implementation;
- calibrated real-provider benchmark suites.

## Security / authority result

V4 does not make a frontier model the sovereign controller. The adaptive layer may choose a model/route, retrieve minimized context, execute cognitive Council roles, or recover an authorized provider session, but it cannot:

- mint or expand capabilities;
- raise an action class ceiling;
- approve A2 execution;
- directly execute model-proposed tools;
- convert consensus/adjudication into verification evidence;
- treat provider-thread state as canonical Universal Brain state;
- bypass passwords, MFA, CAPTCHA, provider rate limits, or anti-bot controls.

Consequential action authority remains behind deterministic Kernel/ToolGateway policy and the existing verification boundary.

## Clean packaging policy

The V4 release artifact is built from the verified working tree while excluding generated/runtime/platform-local material, including:

- `.pytest_cache/`, `__pycache__/`, `*.pyc`, `*.pyo`;
- `console/node_modules/` and frontend `dist/` output;
- `.universal_brain/` local runtime/session/telemetry state;
- `.git/`, virtual environments, coverage/mypy/ruff caches;
- local evidence/runtime `data/` contents.

The packaged repository therefore contains source, tests, documentation, configuration examples, lockfiles, and build metadata, but no copied dependency tree, credentials, authenticated browser profile, or local runtime state.

## Release-package verification

The clean staging tree was created using the packaging exclusions above and checked for required V4 source, test, architecture, ADR, and verification files before compression.

Packaging result:

```text
276 packaged files
ZIP integrity test: PASS
V4 verification record present in final archive: PASS
```

A separate SHA-256 sidecar is generated for the final ZIP so artifact integrity can be checked without creating a checksum/document circular dependency inside the archive.

## Checkpoint conclusion

The **Adaptive Cognitive Control / Intelligence Fabric V4 checkpoint is accepted for packaging** on the evidence above. It is suitable as the next reproducible source checkpoint for continued development of real provider calibration, production verification/tool execution, and authorized end-to-end multi-model missions.
