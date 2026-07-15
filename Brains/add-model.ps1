# Add a local GGUF under Brains/models/ (any model of your choice).
#
# From repo root or from Brains/:
#   .\Brains\add-model.ps1 -Preset deepseek-coder-v2-lite
#   .\Brains\add-model.ps1 -Role coding -Repo "owner/repo-GGUF" -File "Model-Q4_K_M.gguf"
#   .\Brains\add-model.ps1 -ListPresets
#
# Then set the printed env line in PythonScripts/.env and restart start-server.ps1.

param(
    [string]$Preset,
    [ValidateSet("conversational", "coding")]
    [string]$Role,
    [string]$Repo,
    [string]$File,
    [switch]$ListPresets
)

$ErrorActionPreference = "Stop"
$BrainsDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $BrainsDir
$DownloadPy = Join-Path $ProjectRoot "PythonScripts\download_local_model.py"

if (-not (Test-Path $DownloadPy)) {
    Write-Error "Missing $DownloadPy"
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    $py = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $py) {
    Write-Error "Python not found on PATH. Install Python 3 and retry."
}

$argsList = @($DownloadPy)
if ($ListPresets) {
    $argsList += "--list-presets"
}
elseif ($Preset) {
    $argsList += @("--preset", $Preset)
}
else {
    if (-not $Role -or -not $Repo -or -not $File) {
        Write-Host @"
Usage:
  .\add-model.ps1 -Preset deepseek-coder-v2-lite
  .\add-model.ps1 -Role coding -Repo "bartowski/Some-GGUF" -File "Some-Q4_K_M.gguf"
  .\add-model.ps1 -ListPresets
"@
        exit 1
    }
    $argsList += @("--role", $Role, "--repo", $Repo, "--file", $File)
}

& $py.Source @argsList
exit $LASTEXITCODE
