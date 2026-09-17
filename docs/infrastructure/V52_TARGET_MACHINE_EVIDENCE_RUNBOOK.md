# V5.2 Target-Machine Evidence Runbook

**Checkpoint:** Universal Brain V5.2 — Engineering Runtime Hardening  
**Purpose:** Produce real deployment evidence without upgrading unsupported checks into claims.

## Evidence rule

Cross-platform tests prove deterministic implementation behavior. They do **not** prove that a particular Windows host has WSL2, Hyper-V, a production language server, or enough stability for multi-hour autonomous work.

Target evidence is written as a self-digested JSON report with three states:

- `pass` — the requested check actually ran and satisfied its gate;
- `fail` — the check ran (or was required) and failed;
- `skip` — the environment/operator did not provide the capability, so no claim is made.

A Linux CI `skip` for Hyper-V is expected and must never be relabeled `pass`.

## 1. Prepare the Windows checkout

From PowerShell in the V5.2 repository:

```powershell
python --version
python -m pip install -e ".[dev,semantic]"
```

Installing dependencies is an **operator action**. The evidence scripts do not install software themselves.

For the Operator Console, separately run:

```powershell
cd console
npm ci
npm run build
cd ..
```

## 2. Select a production language server

Examples (only use one that is already installed/authorized on the machine):

- Python: `pyright-langserver --stdio`
- C/C++: `clangd`
- Rust: `rust-analyzer`

Choose a real source file inside the repository and its LSP language ID. The V5.2 stdio client will initialize the workspace, open the file, request symbols and diagnostics, then shut the server down. It never applies a WorkspaceEdit.

Example Python probe:

```powershell
./scripts/v52_windows_evidence.ps1 `
  -Workspace . `
  -WslDistro "Ubuntu-24.04" `
  -LspExecutable "pyright-langserver" `
  -LspArgs @("--stdio") `
  -LspFile "src/universal_brain/engineering/semantic.py" `
  -LspLanguageId "python"
```

If a managed Hyper-V VM is already configured:

```powershell
./scripts/v52_windows_evidence.ps1 `
  -Workspace . `
  -WslDistro "Ubuntu-24.04" `
  -HyperVVm "UniversalBrain-Sandbox" `
  -LspExecutable "pyright-langserver" `
  -LspArgs @("--stdio") `
  -LspFile "src/universal_brain/engineering/semantic.py" `
  -LspLanguageId "python"
```

The probe is read-only with respect to WSL/Hyper-V configuration: it lists WSL distributions, checks `systemd-run`/`unshare`, checks Hyper-V cmdlet availability, and optionally verifies the named VM exists. It does not create a distro/VM or change networking.

## 3. Prove the authority-gated isolation execution path

The production path is:

```text
WSL2IsolationProvider / HyperVIsolationProvider
        ↓
validated IsolationCommandPlan
        ↓
IsolationPlanExecutionTool.register_plan()
        ↓ opaque one-time plan_id
ToolGateway + capability token
        ↓
ToolGatewayIsolationBackend
        ↓
Windows host process
```

Important properties:

- ToolGateway receives an opaque one-time plan ID, not an arbitrary model-authored PowerShell command.
- The execution tool requires an authorized WSL distro or Hyper-V VM.
- Plans missing CPU/RAM/PID/wall-time/network controls fail closed.
- Plan IDs are consumed once and cannot be replayed.

A target deployment should capture ToolGateway `TOOL_CALLED` and `EVIDENCE_PRODUCED` events for at least one bounded WSL2 and/or Hyper-V command before claiming production isolation evidence.

## 4. Run a short endurance smoke first

Example 10-minute smoke of the V5.2 engineering gates:

```powershell
python scripts/v52_endurance.py `
  --workspace . `
  --duration-hours 0.1667 `
  --command-json '["python","-m","pytest","-q","tests/unit/test_engineering_agency_v52.py","tests/unit/test_engineering_lsp_runtime.py","tests/unit/test_engineering_isolation_tool.py","tests/unit/test_engineering_target_evidence.py"]'
```

A short run proves only that the endurance harness works. It does **not** satisfy the multi-hour gate.

## 5. Run the multi-hour evidence gate

The V5.2 gate requires at least **2 hours** of passing elapsed runtime.

Example:

```powershell
python scripts/v52_endurance.py `
  --workspace . `
  --duration-hours 2.25 `
  --cycle-delay-seconds 10 `
  --command-json '["python","-m","pytest","-q","tests/unit/test_engineering_agency_v52.py","tests/unit/test_engineering_lsp_runtime.py","tests/unit/test_engineering_isolation_tool.py","tests/unit/test_engineering_target_evidence.py"]'
```

For stronger evidence, replace the cycle command with the real repository/mission smoke command that exercises your configured Ollama workers, worktrees, merge verification, semantic indexing, and sandbox runtime.

The record is written by default to:

```text
.brain/evidence/v52-endurance.json
```

Per-cycle stdout/stderr/meta files are stored alongside it with SHA-256 digests.

## 6. Produce the final target evidence report

After the endurance run:

```powershell
./scripts/v52_windows_evidence.ps1 `
  -Workspace . `
  -WslDistro "Ubuntu-24.04" `
  -HyperVVm "UniversalBrain-Sandbox" `
  -LspExecutable "pyright-langserver" `
  -LspArgs @("--stdio") `
  -LspFile "src/universal_brain/engineering/semantic.py" `
  -LspLanguageId "python" `
  -EnduranceRecord ".brain/evidence/v52-endurance.json" `
  -Strict
```

The final report is:

```text
.brain/evidence/v52-target-evidence.json
```

Verify `report_sha256` by loading the report through `TargetMachineEvidenceReport.verify_digest()` or rerunning the collector.

## 7. What is required before saying "production proven"

Do not use that label until evidence exists for the deployment configuration actually used in production. At minimum:

1. real Tree-sitter parser loaded;
2. real language server responding on a real repository;
3. actual WSL2 or Hyper-V isolation command executed through the ToolGateway path;
4. requested resource/network controls independently confirmed on that host;
5. several workers exercising generation-fenced leases and isolated worktrees;
6. merged-tree verification during real branch integration;
7. persistent service lifecycle exercised;
8. >=2 hour passing real-repository endurance record;
9. all applicable full-suite dependencies installed and repository tests green.

Until those gates are satisfied, the correct label remains:

> **Cross-Platform Verified Checkpoint / Target-Machine Evidence Pending**
