param(
    [Parameter(Mandatory=$false)][string]$Workspace = (Get-Location).Path,
    [Parameter(Mandatory=$false)][string]$WslDistro = "",
    [Parameter(Mandatory=$false)][string]$HyperVVm = "",
    [Parameter(Mandatory=$false)][string]$LspExecutable = "",
    [Parameter(Mandatory=$false)][string[]]$LspArgs = @(),
    [Parameter(Mandatory=$false)][string]$LspFile = "",
    [Parameter(Mandatory=$false)][string]$LspLanguageId = "",
    [Parameter(Mandatory=$false)][string[]]$OllamaModels = @(),
    [Parameter(Mandatory=$false)][string]$OllamaUrl = "http://127.0.0.1:11434",
    [Parameter(Mandatory=$false)][string]$EnduranceRecord = "",
    [Parameter(Mandatory=$false)][string]$WslLinuxWorkspace = "",
    [switch]$EnableServiceWorkload,
    [switch]$EnableRestartProbe,
    [switch]$EnableOllamaPressure,
    [switch]$Resume,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$arguments = @("scripts/v53_validate.py", "--workspace", $Workspace, "--ollama-url", $OllamaUrl)
if ($WslDistro) { $arguments += @("--wsl-distro", $WslDistro) }
if ($HyperVVm) { $arguments += @("--hyperv-vm", $HyperVVm) }
if ($LspExecutable) {
    $arguments += @("--lsp-executable", $LspExecutable)
    foreach ($arg in $LspArgs) { $arguments += @("--lsp-arg", $arg) }
    if ($LspFile) { $arguments += @("--lsp-file", $LspFile) }
    if ($LspLanguageId) { $arguments += @("--lsp-language-id", $LspLanguageId) }
}
foreach ($model in $OllamaModels) { $arguments += @("--ollama-model", $model) }
if ($EnduranceRecord) { $arguments += @("--endurance-record", $EnduranceRecord) }
if ($WslLinuxWorkspace) { $arguments += @("--wsl-linux-workspace", $WslLinuxWorkspace) }
if ($EnableServiceWorkload) { $arguments += "--enable-service-workload" }
if ($EnableRestartProbe) { $arguments += "--enable-restart-probe" }
if ($EnableOllamaPressure) { $arguments += "--enable-ollama-pressure" }
if ($Resume) { $arguments += "--resume" }
if ($Strict) { $arguments += "--strict" }

Write-Host "Universal Brain V5.3 real-environment validation"
Write-Host "Workspace: $Workspace"
Write-Host "This script does not install dependencies, create VMs, modify WSL/Hyper-V policy, or bypass authentication."
& python @arguments
exit $LASTEXITCODE
