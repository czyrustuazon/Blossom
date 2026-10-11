#!/usr/bin/env pwsh
# Start the Blossom Agent Execution sandbox (Docker)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
docker compose up --build -d
Write-Host "Agent sandbox: http://127.0.0.1:8082/health"
