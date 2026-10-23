# Blossom - run the backend test suite (includes the Companion/Assistant bleed tripwires).
# Tests use a throwaway Mind folder (PythonScripts/conftest.py); the real Mind/ is never touched.
#
#   .\run_tests.ps1            full suite
#   .\run_tests.ps1 -BleedOnly just the client-isolation regression tests

param(
    [switch]$BleedOnly
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path $ProjectRoot "PythonScripts"

$targets = @()
if ($BleedOnly) {
    $targets = @(
        "tests/test_surface_bleed_e2e.py",
        "tests/test_mind_store_migration.py",
        "test_persona_chat_history.py"
    )
}

Push-Location $ScriptsDir
try {
    & python -m pytest -q -p no:cacheprovider @targets
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
