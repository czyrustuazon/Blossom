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
# In-repo Voice service (override with VOICE_DIR if needed)
$VoiceRootDefault = Join-Path $ProjectRoot "Voice"
$VoiceProc = $null

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python was not found on PATH."
}

function Test-BlossomEnvFlag([string]$Value) {
    if (-not $Value) { return $false }
    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLowerInvariant()
}

function Resolve-BlossomPython {
    # Optional override, else same `python` used for ChatRouter (no Voice/.venv required).
    if ($env:VOICE_PYTHON -and (Test-Path -LiteralPath $env:VOICE_PYTHON)) {
        return $env:VOICE_PYTHON
    }
    return $python.Source
}

function Test-BlossomVoiceImports([string]$PythonExe) {
    # fairseq logs INFO to stderr. PowerShell can turn that into NativeCommandError
    # under $ErrorActionPreference=Stop. Run via cmd so only the exit code matters.
    $code = "import torch, fastapi, edge_tts, style_bert_vits2, rvc_python"
    $tmp = [System.IO.Path]::GetTempFileName() + ".py"
    try {
        Set-Content -LiteralPath $tmp -Value $code -Encoding ASCII
        $quotedPy = '"' + $PythonExe + '"'
        $quotedTmp = '"' + $tmp + '"'
        cmd.exe /c "$quotedPy $quotedTmp >nul 2>&1"
        return ($LASTEXITCODE -eq 0)
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Find-BlossomVoicePython([string]$VoiceRoot) {
    $candidates = @()
    $resolved = Resolve-BlossomPython
    if ($resolved) { $candidates += $resolved }
    $candidates += (Join-Path $VoiceRoot ".venv\Scripts\python.exe")
    # Sibling leftover from older layout: Documents\Voice\.venv
    $sibling = Join-Path (Split-Path -Parent $ProjectRoot) "Voice\.venv\Scripts\python.exe"
    $candidates += $sibling

    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        if (Test-BlossomVoiceImports $candidate) {
            return $candidate
        }
    }
    return $null
}

function Start-BlossomVoiceService {
    param(
        [string]$VoiceRoot,
        [string]$HostAddr = "127.0.0.1",
        [string]$Port = "8090"
    )
    if (-not (Test-Path -LiteralPath (Join-Path $VoiceRoot "service.py"))) {
        Write-Warning "VOICE_ENABLED but service.py not found in: $VoiceRoot"
        return $null
    }
    $py = Find-BlossomVoicePython -VoiceRoot $VoiceRoot
    if (-not $py) {
        Write-Warning "Voice deps not found on PATH python (or legacy .venv)."
        Write-Warning "From Voice\: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124"
        Write-Warning "Then: pip install -r requirements.txt"
        return $null
    }
    Write-Host "Starting Voice service on http://${HostAddr}:${Port} ..."
    Write-Host "  Root: $VoiceRoot"
    Write-Host "  Python: $py"
    $proc = Start-Process -FilePath $py `
        -ArgumentList @("-m", "uvicorn", "service:app", "--host", $HostAddr, "--port", $Port) `
        -WorkingDirectory $VoiceRoot `
        -WindowStyle Hidden `
        -PassThru
    Write-Host "  Voice PID $($proc.Id)"
    return $proc
}

function Stop-BlossomVoiceService {
    param($Proc)
    if (-not $Proc) { return }
    try {
        if (-not $Proc.HasExited) {
            Write-Host "Stopping Voice service PID $($Proc.Id) ..."
            Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
            # uvicorn may spawn a child; best-effort clear listeners on the voice port
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.ParentProcessId -eq $Proc.Id -or
                    ($_.CommandLine -and $_.CommandLine -match "uvicorn\s+service:app")
                } |
                ForEach-Object {
                    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                }
        }
    } catch {
        Write-Warning "Could not stop Voice service: $_"
    }
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
Write-Host "History compaction runs after ChatRouter brings llama-server up (needs :11434)."
Write-Host ""

if (-not $env:GEMINI_API_KEY -and -not $env:CLAUDE_API_KEY -and -not $env:ANTHROPIC_API_KEY) {
    Write-Warning "No cloud keys set (CLAUDE_API_KEY / GEMINI_API_KEY). Last-resort fallback unavailable."
} elseif (-not $env:CLAUDE_API_KEY -and -not $env:ANTHROPIC_API_KEY) {
    Write-Warning "CLAUDE_API_KEY is not set. Claude last-resort fallback unavailable."
} elseif (-not $env:GEMINI_API_KEY) {
    Write-Warning "GEMINI_API_KEY is not set. Gemini last-resort fallback unavailable."
}

$routerHost = if ($env:CHAT_ROUTER_HOST) { $env:CHAT_ROUTER_HOST } else { "127.0.0.1" }
$routerPort = if ($env:CHAT_ROUTER_PORT) { $env:CHAT_ROUTER_PORT } else { "8081" }

$voiceRoot = if ($env:VOICE_DIR) { $env:VOICE_DIR } else { $VoiceRootDefault }
$voiceHost = "127.0.0.1"
$voicePort = "8090"
if ($env:VOICE_SERVICE_URL -match "^https?://([^:/]+):(\d+)") {
    $voiceHost = $Matches[1]
    $voicePort = $Matches[2]
} elseif ($env:VOICE_PORT) {
    $voicePort = $env:VOICE_PORT
}

Write-Host ""
if (Test-BlossomEnvFlag $env:VOICE_ENABLED) {
    $VoiceProc = Start-BlossomVoiceService -VoiceRoot $voiceRoot -HostAddr $voiceHost -Port $voicePort
    if ($VoiceProc) {
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host "Voice service skipped (VOICE_ENABLED is not true)."
}

Write-Host ""
Write-Host "Starting ChatRouter on http://${routerHost}:${routerPort} ..."
Write-Host "ChatRouter will hot-swap llama-server between persona and coder models."
Write-Host "Point clients at http://${routerHost}:${routerPort}/v1/chat/completions"
Write-Host "(Ctrl+C stops the router, Voice service, and llama-server.)"
Write-Host ""

Enable-BlossomKeepAwake

Push-Location $ScriptsDir
try {
    & python (Join-Path $ScriptsDir "ChatRouter.py")
} finally {
    Disable-BlossomKeepAwake
    Pop-Location
    Stop-BlossomVoiceService -Proc $VoiceProc
    if (Test-Path -LiteralPath $PidFile) {
        $llamaPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
        if ($llamaPid) {
            Write-Host "Stopping llama-server PID $llamaPid ..."
            Stop-Process -Id ([int]$llamaPid) -Force -ErrorAction SilentlyContinue
        }
    }
}
