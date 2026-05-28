Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

Write-Host "[1/3] Running API tests..." -ForegroundColor Cyan
py -3.13 -m pytest .\apps\api\tests

Write-Host "[2/3] Type checking frontend..." -ForegroundColor Cyan
pnpm --dir .\apps\web exec tsc --noEmit

Write-Host "[3/3] Building frontend..." -ForegroundColor Cyan
pnpm --dir .\apps\web build

Write-Host "[bonus] End-to-end smoke test..." -ForegroundColor Cyan
py -3.13 .\scripts\smoke_e2e.py

Write-Host "Checks passed." -ForegroundColor Green
