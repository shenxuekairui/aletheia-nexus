param(
    [switch]$Browser
)

$ErrorActionPreference = "Stop"

function Invoke-AnCheck {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Aletheia Nexus v0.6 release-candidate verification"
python --version
if ($LASTEXITCODE -ne 0) {
    throw "Python is unavailable"
}

Invoke-AnCheck "Installed dependency consistency" {
    python -m pip check
}

Invoke-AnCheck "Ruff formatting" {
    python -m ruff format --check src tests scripts
}

Invoke-AnCheck "Ruff static checks" {
    python -m ruff check src tests scripts
}

Invoke-AnCheck "Python syntax / bytecode compilation" {
    python -m compileall -q src scripts
}

Invoke-AnCheck "Frozen 20-paper benchmark integrity" {
    python scripts/verify_frozen_benchmark.py
}

Invoke-AnCheck "Deterministic test suite" {
    python -m pytest -q
}

if ($Browser) {
    Invoke-AnCheck "Playwright Chromium smoke" {
        python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); page=b.new_page(); page.set_content('<title>AN browser smoke</title><main>ok</main>'); assert page.title() == 'AN browser smoke'; assert page.locator('main').inner_text() == 'ok'; b.close(); p.stop()"
    }

    $previous = $env:AN_RUN_BROWSER_SMOKE
    try {
        $env:AN_RUN_BROWSER_SMOKE = "1"
        Invoke-AnCheck "Access-layer browser integration tests" {
            python -m pytest -q tests/acquire/access
        }
    }
    finally {
        $env:AN_RUN_BROWSER_SMOKE = $previous
    }
}

Write-Host ""
Write-Host "ALL REQUESTED v0.6 RC CHECKS PASSED"
