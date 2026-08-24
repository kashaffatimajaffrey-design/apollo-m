# Start the APOLLO-M monitoring stack: exporter -> Prometheus -> Grafana.
#
# The three pieces are separate processes and none of them survives a reboot, so
# "Grafana won't load" almost always means nothing was started rather than
# anything being broken. This brings all three up in the right order and waits
# for each port before starting the next, because Grafana provisions its
# datasource against Prometheus at boot and Prometheus needs the exporter to be
# answering before its first scrape.
#
#   powershell -ExecutionPolicy Bypass -File monitoring\start_monitoring.ps1
#
# Then:  Grafana http://localhost:3000  ·  Prometheus http://localhost:9090
#        exporter http://localhost:9100/metrics
#
# Stop everything with:  monitoring\stop_monitoring.ps1

param(
    # benchmark | real — which corpus the exporter reflects. Must match what the
    # API and database serve, or Grafana will disagree with the dashboard.
    [string]$Dataset = "real"
)

$ErrorActionPreference = "Stop"
$mon  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $mon
$prom = Get-ChildItem "$mon\bin" -Directory -Filter "prometheus-*" | Select-Object -First 1
$graf = Get-ChildItem "$mon\bin" -Directory -Filter "grafana-*"    | Select-Object -First 1

if (-not $prom) { throw "Prometheus binary missing. Run monitoring\get_binaries.ps1 first." }
if (-not $graf) { throw "Grafana binary missing. Run monitoring\get_binaries.ps1 first." }

function Wait-Port([int]$Port, [string]$Name, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($ok) { Write-Host "  $Name is up on :$Port" -ForegroundColor Green; return $true }
        Start-Sleep -Milliseconds 700
    }
    Write-Host "  $Name did NOT come up on :$Port within $TimeoutSec s" -ForegroundColor Yellow
    return $false
}

function Test-Running([int]$Port) {
    Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
}

New-Item -ItemType Directory -Force "$mon\logs" | Out-Null

# ── 1. Exporter — reads the pipeline's CSVs and serves gauges on :9100 ───────
if (Test-Running 9100) {
    Write-Host "exporter already running on :9100" -ForegroundColor DarkGray
} else {
    Write-Host "starting exporter (dataset: $Dataset) ..."
    $env:APOLLO_DATASET = $Dataset
    Start-Process -FilePath "python" `
        -ArgumentList "`"$mon\exporter.py`"" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$mon\logs\exporter.out.log" `
        -RedirectStandardError  "$mon\logs\exporter.err.log"
    Wait-Port 9100 "exporter" 45 | Out-Null
}

# ── 2. Prometheus — scrapes :9100 every 5s and stores the history ────────────
if (Test-Running 9090) {
    Write-Host "Prometheus already running on :9090" -ForegroundColor DarkGray
} else {
    Write-Host "starting Prometheus ..."
    Start-Process -FilePath "$($prom.FullName)\prometheus.exe" `
        -ArgumentList @(
            "--config.file=$mon\prometheus-native.yml",
            "--storage.tsdb.path=$mon\bin\prometheus-data",
            "--web.listen-address=:9090"
        ) -WorkingDirectory $prom.FullName -WindowStyle Hidden `
        -RedirectStandardOutput "$mon\logs\prometheus.out.log" `
        -RedirectStandardError  "$mon\logs\prometheus.err.log"
    Wait-Port 9090 "Prometheus" 45 | Out-Null
}

# ── 3. Grafana — provisioned with the Prometheus datasource + APOLLO board ───
if (Test-Running 3000) {
    Write-Host "Grafana already running on :3000" -ForegroundColor DarkGray
} else {
    Write-Host "starting Grafana ..."
    # Provisioning is picked up from our folder, not Grafana's own conf/, so the
    # datasource and the APOLLO-M dashboard exist on a clean install with no
    # clicking through the UI.
    $env:GF_PATHS_PROVISIONING = "$mon\grafana-provisioning"
    $env:GF_PATHS_DATA         = "$($graf.FullName)\data"
    $env:GF_PATHS_LOGS         = "$mon\logs"
    $env:GF_SERVER_HTTP_PORT   = "3000"
    Start-Process -FilePath "$($graf.FullName)\bin\grafana.exe" `
        -ArgumentList @("server", "--homepath", "$($graf.FullName)") `
        -WorkingDirectory $graf.FullName -WindowStyle Hidden `
        -RedirectStandardOutput "$mon\logs\grafana.out.log" `
        -RedirectStandardError  "$mon\logs\grafana.err.log"
    Wait-Port 3000 "Grafana" 90 | Out-Null
}

Write-Host ""
Write-Host "=== APOLLO-M monitoring ===" -ForegroundColor Cyan
foreach ($svc in @(@(9100, "exporter   http://localhost:9100/metrics"),
                   @(9090, "Prometheus http://localhost:9090"),
                   @(3000, "Grafana    http://localhost:3000"))) {
    $up = Test-Running $svc[0]
    $mark = if ($up) { "UP  " } else { "DOWN" }
    $col  = if ($up) { "Green" } else { "Yellow" }
    Write-Host "  [$mark] $($svc[1])" -ForegroundColor $col
}
Write-Host ""
Write-Host "Grafana login: admin / apollo_pass  (Grafana keeps its own account)" -ForegroundColor DarkGray
Write-Host "Logs in monitoring\logs\" -ForegroundColor DarkGray
