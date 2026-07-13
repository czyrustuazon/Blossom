# Blossom — starts memory compaction, then ChatRouter (owns llama-server hot-swap).
# Works no matter where the project folder is moved.

$ErrorActionPreference = "Stop"

# Keep the system awake while ChatRouter runs (screen may still turn off).
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class BlossomKeepAwake {
    private const uint ES_CONTINUOUS = 0x80000000;
    private const uint ES_SYSTEM_REQUIRED = 0x00000001;
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public static void Enable() {
        SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED);
    }
    public static void Disable() {
        SetThreadExecutionState(ES_CONTINUOUS);
    }
}
"@ -ErrorAction SilentlyContinue

function Enable-BlossomKeepAwake {
    try {
        [BlossomKeepAwake]::Enable()
        Write-Host "Keep-awake: ON (PC won't sleep until ChatRouter stops)."
    } catch {
        Write-Warning "Could not enable keep-awake: $_"
    }
}

function Disable-BlossomKeepAwake {
    try {
        [BlossomKeepAwake]::Disable()
        Write-Host "Keep-awake: OFF."
    } catch {
        Write-Warning "Could not disable keep-awake: $_"
    }
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path $ProjectRoot "PythonScripts"
$PidFile = Join-Path $ProjectRoot "Mind\llama-server.pid"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python was not found on PATH."
}

# Surface .env values into this PowerShell process (project .env always wins).
$EnvFile = Join-Path $ScriptsDir ".env"
if (Test-Path -LiteralPath $EnvFile) {
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
        $key, $value = $line.Split("=", 2)
        $key = $key.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if (-not $key) { return }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
        Set-Item -Path "Env:$key" -Value $value
    }
}

Write-Host "Blossom project : $ProjectRoot"
Write-Host "Scripts         : $ScriptsDir"
Write-Host ""

Write-Host "Running HistoryCompactor.py..."
& python (Join-Path $ScriptsDir "HistoryCompactor.py")
if ($LASTEXITCODE -ne 0) {
    Write-Warning "HistoryCompactor exited with code $LASTEXITCODE"
}

if (-not $env:GEMINI_API_KEY -and -not $env:CLAUDE_API_KEY -and -not $env:ANTHROPIC_API_KEY) {
    Write-Warning "No cloud keys set (CLAUDE_API_KEY / GEMINI_API_KEY). Last-resort fallback unavailable."
} elseif (-not $env:CLAUDE_API_KEY -and -not $env:ANTHROPIC_API_KEY) {
    Write-Warning "CLAUDE_API_KEY is not set. Claude last-resort fallback unavailable."
} elseif (-not $env:GEMINI_API_KEY) {
    Write-Warning "GEMINI_API_KEY is not set. Gemini last-resort fallback unavailable."
}

$routerHost = if ($env:CHAT_ROUTER_HOST) { $env:CHAT_ROUTER_HOST } else { "127.0.0.1" }
$routerPort = if ($env:CHAT_ROUTER_PORT) { $env:CHAT_ROUTER_PORT } else { "8081" }

Write-Host ""
Write-Host "Starting ChatRouter on http://${routerHost}:${routerPort} ..."
Write-Host "ChatRouter will hot-swap llama-server between persona and coder models."
Write-Host "Point clients at http://${routerHost}:${routerPort}/v1/chat/completions"
Write-Host "(Ctrl+C stops the router and llama-server.)"
Write-Host ""

Enable-BlossomKeepAwake

Push-Location $ScriptsDir
try {
    & python (Join-Path $ScriptsDir "ChatRouter.py")
} finally {
    Disable-BlossomKeepAwake
    Pop-Location
    if (Test-Path -LiteralPath $PidFile) {
        $llamaPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
        if ($llamaPid) {
            Write-Host "Stopping llama-server PID $llamaPid ..."
            Stop-Process -Id ([int]$llamaPid) -Force -ErrorAction SilentlyContinue
        }
    }
}
