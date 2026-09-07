Set-Location $PSScriptRoot

# The walk-test and AR path use the validated accelerated stack by default.
# Explicit environment values still win, so NAV_ACCEL=0 remains available for
# a controlled ORB/torch comparison run.
if (-not $env:NAV_ACCEL) { $env:NAV_ACCEL = '1' }
if (-not $env:NAV_MATCHING_MODE) { $env:NAV_MATCHING_MODE = 'superpoint' }
if (-not $env:NAV_RETRIEVAL_MODE) { $env:NAV_RETRIEVAL_MODE = 'megaloc' }

$backendPort = 5000
if ($env:NAV_SERVER_PORT) {
    $parsedPort = 0
    if ([int]::TryParse($env:NAV_SERVER_PORT, [ref]$parsedPort)) {
        $backendPort = $parsedPort
    }
}

$autoFreePort = $true
if ($env:NAV_AUTO_FREE_PORT) {
    $autoFreePort = $env:NAV_AUTO_FREE_PORT.ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
}

function Stop-ListeningProcessesOnPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        return
    }

    $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    Write-Host "[run_backend] Port $Port is in use. Stopping existing process(es): $($ownerIds -join ', ')"

    foreach ($ownerId in $ownerIds) {
        try {
            $existingProcess = Get-Process -Id $ownerId -ErrorAction Stop
            Stop-Process -Id $ownerId -Force -ErrorAction Stop
            Write-Host "[run_backend] Stopped PID=$ownerId ($($existingProcess.ProcessName))"
        } catch {
            Write-Warning "[run_backend] Failed to stop PID=$ownerId on port ${Port}: $($_.Exception.Message)"
        }
    }

    Start-Sleep -Milliseconds 500

    $stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($stillListening) {
        throw "[run_backend] Port $Port is still in use after cleanup."
    }
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
        throw "[run_backend] Port $Port is already in use by PID(s): $($ownerIds -join ', '). Set NAV_AUTO_FREE_PORT=1 to auto-stop."
    }
}

if ($autoFreePort) {
    Stop-ListeningProcessesOnPort -Port $backendPort
} else {
    Assert-PortAvailable -Port $backendPort
}

$uvicornArgs = @(
    '-m', 'uvicorn',
    'app.main:app',
    '--host', '0.0.0.0',
    '--port', "$backendPort"
)

Write-Host "[run_backend] Starting backend on port $backendPort (auto_free_port=$autoFreePort)"

if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" @uvicornArgs
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @uvicornArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @uvicornArgs
} else {
    Write-Error "Python not found in PATH."
    exit 1
}

exit $LASTEXITCODE
