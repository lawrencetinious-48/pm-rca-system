Param(
    [string]$Mode = "test-only"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$venvExe = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvExe) { $python = $venvExe } else { $python = "python" }

if ($Mode -eq 'bootstrap') {
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtualenv .venv..."
        & $python -m venv .venv
        $venvExe = Join-Path $root ".venv\Scripts\python.exe"
        if (Test-Path $venvExe) { $python = $venvExe }
    }
    Write-Host "Upgrading pip and installing requirements..."
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}

Write-Host "Using Python: $($python)"

if ($Mode -in @('test-only','bootstrap')) {
    Write-Host "Running tests: pytest tests"
    & $python -m pytest tests -q --maxfail=10
    $testExit = $LASTEXITCODE
} else {
    $testExit = 0
}

Write-Host "Running health check (if present)..."
if (Test-Path scripts\health_check.py) {
    & $python scripts\health_check.py
    $hcExit = $LASTEXITCODE
} else { $hcExit = 0 }

Write-Host "Running flake8 lint..."
$flakeExit = 0
try {
    flake8 .
    $flakeExit = $LASTEXITCODE
} catch {
    Write-Host "flake8 not available or failed; install in venv to enable linting."
}

Write-Host "RESULTS: tests=$testExit, health=$hcExit, flake=$flakeExit"
exit ($testExit -bor $hcExit -bor $flakeExit)
