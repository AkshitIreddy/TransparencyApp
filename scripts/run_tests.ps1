# Sandboxed test runner: pytest runs on a hidden Windows desktop (via
# scripts/sandbox_run.py), so its windows can never appear on screen, and a
# hard watchdog force-kills the tree on timeout. Never run pytest bare on a
# dev machine - it creates real Win32 windows.
#
# Uses the bare `pytest` console script (like CI does) so this wrapper catches
# import-path problems that `python -m pytest` would mask.
param(
    [int]$TimeoutSec = 90,
    [string]$PytestArgs = "tests -q"
)

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$pytest = Join-Path $repo ".venv\Scripts\pytest.exe"
if (-not (Test-Path $python)) { $python = "python" }
if (-not (Test-Path $pytest)) { $pytest = "pytest" }
$results = Join-Path $env:TEMP "ta_test_results.txt"
if (Test-Path $results) { Remove-Item $results -Force }

$argList = @("scripts\sandbox_run.py", "$TimeoutSec", "--", $pytest) +
           ($PytestArgs -split " ") + @(">", $results, "2>&1")
& $python @argList
$code = $LASTEXITCODE

# Safety net: reap any stray venv pythons left behind by a crash.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.ExecutablePath -like "*TransparencyApp\.venv*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { taskkill /T /F /PID $_.ProcessId 2>$null | Out-Null }

Write-Output "--- results (tail) ---"
if (Test-Path $results) { Get-Content $results -Tail 30 }
Write-Output "exitcode=$code"
exit $code
