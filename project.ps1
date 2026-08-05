[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "setup", "backup")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime"
$BackendLog = Join-Path $RuntimeRoot "backend.log"
$BackendErrorLog = Join-Path $RuntimeRoot "backend-error.log"
$FrontendLog = Join-Path $RuntimeRoot "frontend.log"
$FrontendErrorLog = Join-Path $RuntimeRoot "frontend-error.log"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-ListenerProcess([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { return $listener.OwningProcess }
    return $null
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return $response }
        } catch { Start-Sleep -Milliseconds 750 }
    }
    return $null
}

function Get-ProjectPython {
    $candidates = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot ".venv-codex\Scripts\python.exe"),
        (Join-Path $ProjectRoot ".venv-run\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            & $candidate -c "import fastapi, httpx, uvicorn" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {
            continue
        }
    }
    return $null
}

function Install-Project {
    Write-Step "Preparando o backend"
    $python = Get-ProjectPython
    if (-not $python) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            & $launcher.Source -3.12 -m venv (Join-Path $ProjectRoot ".venv")
        } else {
            $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $systemPython) { throw "Python não encontrado. Instale Python 3.12 ou 3.13." }
            & $systemPython.Source -m venv (Join-Path $ProjectRoot ".venv")
        }
        if ($LASTEXITCODE -ne 0) { throw "Não foi possível criar o ambiente Python." }
        $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    }
    & $python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências do backend." }

    Write-Step "Preparando o frontend"
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw "Node.js não encontrado. Instale a versão LTS do Node.js." }
    Push-Location $FrontendRoot
    try {
        npm.cmd install
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências do frontend." }
    } finally { Pop-Location }
    Write-Host "Ambiente preparado." -ForegroundColor Green
}

function Test-TrafegusNetwork {
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) { throw "Arquivo .env ausente. Copie .env.example para .env e preencha as credenciais." }
    $urlLine = Get-Content $envFile | Where-Object { $_ -match '^\s*TRAFEGUS_API_URL\s*=' } | Select-Object -First 1
    $url = if ($urlLine) { ($urlLine -split '=', 2)[1].Trim().Trim('"').Trim("'") } else { "https://sevencargo.trafegus.com.br/ws_rest/public/api" }
    $uri = [Uri]$url
    $port = if ($uri.IsDefaultPort) { 443 } else { $uri.Port }
    if (-not (Test-NetConnection $uri.Host -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue)) {
        throw "Sem conexão com $($uri.Host):$port. Verifique internet, VPN, firewall ou proxy."
    }
}

function Stop-Project {
    Write-Step "Parando o projeto"
    foreach ($port in 5173, 8000) {
        $processId = Get-ListenerProcess $port
        if ($processId) {
            & taskkill.exe /PID $processId /T /F | Out-Null
            Write-Host "Porta $port liberada (PID $processId)."
        } else { Write-Host "Porta $port já estava livre." }
    }
}

function Show-Status {
    $backend = Get-ListenerProcess 8000
    $frontend = Get-ListenerProcess 5173
    Write-Host "Backend : $(if ($backend) { "rodando (PID $backend)" } else { "parado" })"
    Write-Host "Frontend: $(if ($frontend) { "rodando (PID $frontend)" } else { "parado" })"
    if ($backend) {
        try {
            $integration = Invoke-RestMethod -Uri "http://127.0.0.1:8000/integrations/status" -TimeoutSec 10
            Write-Host "Trafegus : $($integration.trafegus)"
        } catch { Write-Host "Trafegus : não foi possível consultar" -ForegroundColor Yellow }
    }
}

function Start-Project {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    if ((Get-ListenerProcess 8000) -or (Get-ListenerProcess 5173)) {
        Write-Host "O projeto ou outro processo já usa as portas necessárias:" -ForegroundColor Yellow
        Show-Status
        Write-Host "Use 'project.cmd restart' para reiniciar com segurança."
        return
    }
    $python = Get-ProjectPython
    if (-not $python -or -not (Test-Path (Join-Path $FrontendRoot "node_modules"))) {
        Install-Project
        $python = Get-ProjectPython
    }
    Test-TrafegusNetwork

    Write-Step "Iniciando backend"
    $backend = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErrorLog
    if (-not (Wait-Http "http://127.0.0.1:8000/health" 35)) { throw "O backend não iniciou. Consulte $BackendErrorLog" }

    Write-Step "Validando autenticação no Trafegus"
    try {
        $fleet = Invoke-WebRequest -Uri "http://127.0.0.1:8000/fleet/active" -UseBasicParsing -TimeoutSec 60
        if ($fleet.StatusCode -ne 200) { throw "HTTP $($fleet.StatusCode)" }
    } catch {
        & taskkill.exe /PID $backend.Id /T /F | Out-Null
        throw "O Trafegus não ficou operacional: $($_.Exception.Message). Consulte $BackendErrorLog"
    }

    Write-Step "Iniciando frontend"
    $vite = Join-Path $FrontendRoot "node_modules\.bin\vite.cmd"
    $frontend = Start-Process -FilePath $vite -ArgumentList "--host", "0.0.0.0" -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErrorLog
    if (-not (Wait-Http "http://127.0.0.1:5173" 35)) {
        & taskkill.exe /PID $frontend.Id /T /F | Out-Null
        & taskkill.exe /PID $backend.Id /T /F | Out-Null
        throw "O frontend não iniciou. Consulte $FrontendErrorLog"
    }
    Write-Host "`nProjeto pronto." -ForegroundColor Green
    Write-Host "Painel:   http://localhost:5173"
    Write-Host "API:      http://localhost:8000"
    Write-Host "Trafegus: operacional"
    Write-Host "Logs:     $RuntimeRoot"
}

try {
    switch ($Action) {
        "setup" { Install-Project }
        "start" { Start-Project }
        "stop" { Stop-Project }
        "restart" { Stop-Project; Start-Sleep -Seconds 1; Start-Project }
        "status" { Show-Status }
        "backup" {
            $python = Get-ProjectPython
            if (-not $python) { throw "Ambiente Python não disponível. Execute 'project.cmd setup'." }
            & $python -m app.scripts.backup_operations --label manual
            if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o backup operacional." }
        }
    }
} catch {
    Write-Host "`nERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
