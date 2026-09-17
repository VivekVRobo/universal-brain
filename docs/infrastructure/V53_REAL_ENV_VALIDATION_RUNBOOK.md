# V5.3 Real-Environment Validation Runbook

**Checkpoint:** Universal Brain V5.3 — Real-Environment Validation & Endurance  
**Target:** the operator's Windows development machine

## 1. Install declared dependencies manually

From the repository in PowerShell:

```powershell
python -m pip install -e ".[dev,semantic]"
```

The validation harness never installs dependencies itself.

For the console, separately:

```powershell
cd console
npm ci
npm run build
cd ..
```

## 2. Identify the three actual Ollama model names

```powershell
ollama list
```

Use the exact names in the validation command. Do not guess model aliases.

## 3. Identify WSL2 and a production language server

```powershell
wsl --list --verbose
pyright-langserver --version
```

Example Windows checkout:

```text
C:\Users\vivek\Desktop\universal-brain
```

might map inside WSL to:

```text
/mnt/c/Users/vivek/Desktop/universal-brain
```

Use the real mapping for your machine.

## 4. Run the target validation

Example with three Ollama models, pyright, WSL2 execution, real service lifecycle, and process-restart proof:

```powershell
.\scripts\v53_windows_validate.ps1 `
  -Workspace . `
  -WslDistro "Ubuntu-24.04" `
  -WslLinuxWorkspace "/mnt/c/Users/vivek/Desktop/universal-brain" `
  -LspExecutable "pyright-langserver" `
  -LspArgs @("--stdio") `
  -LspFile "src/universal_brain/engineering/semantic.py" `
  -LspLanguageId "python" `
  -OllamaModels @("MODEL_1","MODEL_2","MODEL_3") `
  -EnableServiceWorkload `
  -EnableRestartProbe
```

This does **not** enable concurrent model pressure by default.

## 5. Optional bounded three-model pressure

Only after checking available RAM/VRAM:

```powershell
.\scripts\v53_windows_validate.ps1 `
  -Workspace . `
  -OllamaModels @("MODEL_1","MODEL_2","MODEL_3") `
  -EnableOllamaPressure `
  -Resume
```

This sends one tiny concurrent generation to each selected model. Large models may consume substantial memory. It is intentionally opt-in.

## 6. Short mission smoke

Supply the real command that resumes/runs your Engineering Agency mission. Example placeholder only:

```powershell
python scripts/v53_endurance.py `
  --workspace . `
  --duration-hours 0.10 `
  --mission-command-json '["python","YOUR_REAL_MISSION_ENTRYPOINT.py","--resume"]'
```

Replace the placeholder with the actual mission entrypoint configured on the machine.

## 7. Multi-hour gate

After the short smoke succeeds:

```powershell
python scripts/v53_endurance.py `
  --workspace . `
  --duration-hours 2.25 `
  --mission-command-json '["python","YOUR_REAL_MISSION_ENTRYPOINT.py","--resume"]'
```

Then rerun validation with the record:

```powershell
.\scripts\v53_windows_validate.ps1 `
  -Workspace . `
  -WslDistro "Ubuntu-24.04" `
  -WslLinuxWorkspace "/mnt/c/Users/vivek/Desktop/universal-brain" `
  -LspExecutable "pyright-langserver" `
  -LspArgs @("--stdio") `
  -LspFile "src/universal_brain/engineering/semantic.py" `
  -LspLanguageId "python" `
  -OllamaModels @("MODEL_1","MODEL_2","MODEL_3") `
  -EnduranceRecord ".brain\evidence\v53\v53-endurance.json" `
  -EnableServiceWorkload `
  -EnableRestartProbe `
  -Resume `
  -Strict
```

## 8. Verify the evidence bundle offline

```powershell
python scripts/v53_validate.py `
  --workspace . `
  --verify-existing-manifest
```

Expected artifact root:

```text
.brain/evidence/v53/
```

Important files:

- `v53-validation-checkpoint.json`
- `v53-validation-report.json`
- `v53-endurance.json` after endurance
- `v53-evidence-manifest.json`

## Label rule

Until the Windows target report and >=2-hour record verify, use:

> **V5.3 Validation Harness Implemented / Real-Environment Evidence Pending**

Only upgrade the deployment claim after every applicable required check is PASS. A SKIP is never a PASS.
