param(
  [int]$MinAvailMB = 2048,
  [int]$JobMB = 2048,
  [int]$Cooldown = 5,
  [switch]$List
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
  $python = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
  throw "找不到 python；先装 Python 3.11 并加入 PATH。"
}

$argv = @(
  (Join-Path $root "tests\run_safe.py"),
  "--min-avail-mb", "$MinAvailMB",
  "--job-mb", "$JobMB",
  "--cooldown", "$Cooldown"
)
if ($List) { $argv += "--list" }

& $python @argv
exit $LASTEXITCODE
