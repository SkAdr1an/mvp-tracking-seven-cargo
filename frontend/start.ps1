$portableNode = Join-Path $PSScriptRoot ".tools\node-v24.17.0-win-x64"
if (Test-Path (Join-Path $portableNode "node.exe")) {
    $env:Path = "$portableNode;$env:Path"
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js não encontrado. Instale o Node LTS e execute novamente."
    exit 1
}

Set-Location $PSScriptRoot
if (-not (Test-Path "node_modules")) {
    npm.cmd install
}
npm.cmd run dev -- --host 0.0.0.0
