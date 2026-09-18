[CmdletBinding()]
param([ValidateSet("start", "stop", "restart", "dev", "status")][string]$Action = "start")

$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Python = Join-Path $Root "backend\.venv\Scripts\python.exe"

function Listener([int]$Port) {
    (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
}

function Stop-App {
    foreach ($port in 5173, 5174, 8000) {
        $processId = Listener $port
        if ($processId) { taskkill.exe /PID $processId /T /F | Out-Null }
    }
}

function Wait-Url([string]$Url) {
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 750
    }
    return $false
}

function Start-App {
    New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
    if ((Listener 5173) -or (Listener 8000)) { throw "As portas 5173 ou 8000 já estão ocupadas." }
    $env:OPERATIONS_DATABASE_PATH = Join-Path $Root "backend\data\operations.db"
    $backend = Start-Process $Python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime "backend.log") -RedirectStandardError (Join-Path $Runtime "backend-error.log")
    Remove-Item Env:OPERATIONS_DATABASE_PATH
    if (-not (Wait-Url "http://127.0.0.1:8000/health/live")) { throw "Backend não iniciou. Consulte .runtime\backend-error.log" }
    $frontend = Start-Process $Python -ArgumentList (Join-Path $Root "serve_frontend.py") -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime "frontend.log") -RedirectStandardError (Join-Path $Runtime "frontend-error.log")
    if (-not (Wait-Url "http://127.0.0.1:5173")) {
        taskkill.exe /PID $backend.Id /T /F | Out-Null
        throw "Frontend não iniciou. Consulte .runtime\frontend-error.log"
    }
    Write-Host "Versão idêntica à VPS iniciada em http://localhost:5173"
}

function Start-Dev {
    New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
    Stop-App
    $env:OPERATIONS_DATABASE_PATH = Join-Path $Root "backend\data\operations.db"
    $backend = Start-Process $Python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory (Join-Path $Root "backend") -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime "backend.log") -RedirectStandardError (Join-Path $Runtime "backend-error.log")
    Remove-Item Env:OPERATIONS_DATABASE_PATH
    if (-not (Wait-Url "http://127.0.0.1:8000/health/live")) { throw "Backend não iniciou. Consulte .runtime\backend-error.log" }
    $frontend = Start-Process "npm.cmd" -ArgumentList "run","dev","--","--host","127.0.0.1","--port","5174" -WorkingDirectory (Join-Path $Root "frontend-source") -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Runtime "frontend-dev.log") -RedirectStandardError (Join-Path $Runtime "frontend-dev-error.log")
    if (-not (Wait-Url "http://127.0.0.1:5174")) {
        taskkill.exe /PID $backend.Id /T /F | Out-Null
        throw "Frontend de desenvolvimento não iniciou. Consulte .runtime\frontend-dev-error.log"
    }
    Write-Host "Ambiente de desenvolvimento iniciado em http://localhost:5174"
}

switch ($Action) {
    "start" { Start-App }
    "stop" { Stop-App }
    "restart" { Stop-App; Start-Sleep -Seconds 1; Start-App }
    "dev" { Start-Dev }
    "status" { Write-Host "Backend: $(Listener 8000)  Frontend produção: $(Listener 5173)  Frontend dev: $(Listener 5174)" }
}
