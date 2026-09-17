param(
    [Parameter(Mandatory=$false)][string]$Workspace = (Get-Location).Path,
    [Parameter(Mandatory=$false)][string]$WslDistro = "",
    [Parameter(Mandatory=$false)][string]$HyperVVm = "",
    [Parameter(Mandatory=$false)][string]$LspExecutable = "",
    [Parameter(Mandatory=$false)][string[]]$LspArgs = @(),
    [Parameter(Mandatory=$false)][string]$LspFile = "",
    [Parameter(Mandatory=$false)][string]$LspLanguageId = "",
    [Parameter(Mandatory=$false)][string]$EnduranceRecord = "",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$Output = Join-Path $Workspace ".brain\evidence\v52-target-evidence.json"

$arguments = @(
    "scripts/v52_target_evidence.py",
    "--workspace", $Workspace,
    "--output", $Output
)

if ($WslDistro) { $arguments += @("--wsl-distro", $WslDistro) }
if ($HyperVVm) { $arguments += @("--hyperv-vm", $HyperVVm) }
if ($LspExecutable) {
    $arguments += @("--lsp-executable", $LspExecutable)
    foreach ($arg in $LspArgs) { $arguments += @("--lsp-arg", $arg) }
    if ($LspFile) { $arguments += @("--lsp-file", $LspFile) }
    if ($LspLanguageId) { $arguments += @("--lsp-language-id", $LspLanguageId) }
}
if ($EnduranceRecord) { $arguments += @("--endurance-record", $EnduranceRecord) }
if ($Strict) { $arguments += "--strict" }

Write-Host "Universal Brain V5.2 target evidence"
Write-Host "Workspace: $Workspace"
Write-Host "This script does not install packages, create VMs, or change WSL/Hyper-V configuration."
& python @arguments
exit $LASTEXITCODE
