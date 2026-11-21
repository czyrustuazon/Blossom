<#
Alternating A/B of one eval-loop switch against the isolated test router (default port 8093).

  .\run_ab.ps1 -Out C:\scratch\ab1 -Var BLOSSOM_EVAL_HARDEN -Cycles 3
  python ab_summary.py C:\scratch\ab1

Runs <Cycles> pairs: arm "on" (Var=1) then arm "off" (Var=0), alternating so slow drift
(GPU load, model swaps) hits both arms equally. Each cycle writes <Out>\<arm><n>.log and
<Out>\runs\<arm><n>\<task>\ (every round's prompt and reply + transcript.json).

NEVER point this at the real router (8083): ChatRouter saves coder answers as lessons.
See handoff.md "How to run a cycle" for starting the test router on a copy of the Mind.
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Var = "BLOSSOM_EVAL_HARDEN",
    [int]$Cycles = 3,
    [string]$Corpus = "project-refactor",
    [string[]]$Task = @(),
    [int]$Port = 8093,
    [string]$OnValue = "1",
    [string]$OffValue = "0"
)
$ErrorActionPreference = "Stop"
$evalDir = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $evalDir "..\..\PythonScripts\.env"
$hostName = (Select-String -Path $envFile -Pattern '^CHAT_ROUTER_HOST=(.+)$').Matches[0].Groups[1].Value.Trim().Trim('"')
if ($Port -eq 8083) { throw "Port 8083 is the real router. Use the isolated test router." }

New-Item -ItemType Directory -Force $Out | Out-Null
$env:BLOSSOM_EVAL_CHAT_URL = "http://${hostName}:$Port"
$env:PYTHONUNBUFFERED = "1"
$taskArgs = @(); foreach ($t in $Task) { $taskArgs += @("--task", $t) }

Push-Location $evalDir
try {
    foreach ($i in 1..$Cycles) {
        foreach ($arm in @(@("on", $OnValue), @("off", $OffValue))) {
            $name = "$($arm[0])$i"
            Set-Item "env:$Var" $arm[1]
            $ErrorActionPreference = "Continue"   # a failed task exits 1; that is a result, not an error
            python run_eval.py run --corpus $Corpus @taskArgs --db "$Out\results.db" --log-dir "$Out\runs\$name" 2>&1 |
                ForEach-Object { "$_" -replace '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '<ip>' } |
                Set-Content -Encoding utf8 "$Out\$name.log"
            $ErrorActionPreference = "Stop"
            "$name ($Var=$($arm[1])): " + ((Get-Content "$Out\$name.log" | Select-String -Pattern '^Finished') -join ' ')
        }
    }
}
finally {
    Pop-Location
    Remove-Item "env:$Var" -ErrorAction SilentlyContinue
}
