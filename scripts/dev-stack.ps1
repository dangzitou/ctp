Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$python = "py"
try {
  & $python -3.13 --version | Out-Null
} catch {
  throw "Python 3.13 not found. Install it or ensure 'py' launcher is on PATH."
}

Write-Host "Starting API on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$api = Start-Process -FilePath $python `
  -ArgumentList "-m", "uvicorn", "ctp_agent_api.main:app", "--app-dir", "apps/api/src", "--host", "127.0.0.1", "--port", "8000", "--reload" `
  -WorkingDirectory $root `
  -PassThru

Write-Host "Starting Web on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
$web = Start-Process -FilePath "pnpm.cmd" `
  -ArgumentList "--dir", ".\apps\web", "dev", "--host", "127.0.0.1", "--port", "5173" `
  -WorkingDirectory $root `
  -PassThru

Write-Host ""
Write-Host "API PID: $($api.Id)" -ForegroundColor Green
Write-Host "WEB PID: $($web.Id)" -ForegroundColor Green
Write-Host "Use Stop-Process -Id $($api.Id),$($web.Id) to stop them." -ForegroundColor Yellow
