# Download Prometheus + Grafana as native Windows binaries (NOT Docker images).
# Your network only chokes on Docker Hub's CDN; these come from GitHub / grafana.com.
$ErrorActionPreference = "Stop"
$dir = "C:\cerebro_repo (apollo int)\apollo-m\monitoring\bin"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$hdr = @{ "User-Agent" = "apollo-m" }

Write-Host "=== Prometheus ==="
$rel = Invoke-RestMethod "https://api.github.com/repos/prometheus/prometheus/releases/latest" -Headers $hdr
$asset = $rel.assets | Where-Object { $_.name -like "*windows-amd64.zip" } | Select-Object -First 1
Write-Host "downloading" $asset.name
Invoke-WebRequest $asset.browser_download_url -OutFile "$dir\prometheus.zip"
Expand-Archive "$dir\prometheus.zip" -DestinationPath $dir -Force
Remove-Item "$dir\prometheus.zip"
Write-Host "prometheus extracted"

Write-Host "=== Grafana ==="
$grel = Invoke-RestMethod "https://api.github.com/repos/grafana/grafana/releases/latest" -Headers $hdr
$gver = $grel.tag_name.TrimStart('v')
Write-Host "downloading grafana" $gver
Invoke-WebRequest "https://dl.grafana.com/oss/release/grafana-$gver.windows-amd64.zip" -OutFile "$dir\grafana.zip"
Expand-Archive "$dir\grafana.zip" -DestinationPath $dir -Force
Remove-Item "$dir\grafana.zip"
Write-Host "grafana extracted"

Write-Host "=== DONE ==="
Get-ChildItem $dir -Directory | Select-Object -ExpandProperty Name
