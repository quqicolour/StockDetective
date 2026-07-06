# StockDetective - Windows 启动脚本
# 用法：在 PowerShell 里 cd 到 D:\blockchain\ai\StockDetective，然后 .\run.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "[StockDetective] 项目根: $ProjectRoot" -ForegroundColor Cyan

# 1) Python 检查
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "[ERROR] 未找到 python，请先安装 Python 3.10+ 并加入 PATH" -ForegroundColor Red
    Write-Host "下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Python: $($py.Source)" -ForegroundColor Green

# 2) 创建 venv（如果不存在）
$VenvDir = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[..] 创建 venv..." -ForegroundColor Yellow
    python -m venv $VenvDir
} else {
    Write-Host "[OK] venv 已存在" -ForegroundColor Green
}

# 3) 激活 venv
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
. $ActivateScript
Write-Host "[OK] venv 已激活" -ForegroundColor Green

# 4) 装依赖
Write-Host "[..] 装依赖（首次约 1-2 分钟）..." -ForegroundColor Yellow
python -m pip install --upgrade pip -q
python -m pip install -r (Join-Path $ProjectRoot "requirements.txt") -q

# 5) 检查 .env
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[..] .env 不存在，从 .env.example 复制" -ForegroundColor Yellow
    Copy-Item (Join-Path $ProjectRoot ".env.example") $EnvFile
    Write-Host "[!!!] 请编辑 .env 填入 DEEPSEEK_API_KEY 后重新运行" -ForegroundColor Magenta
    notepad $EnvFile
    exit 0
}

# 6) 跑
Write-Host "[..] 启动 StockDetective..." -ForegroundColor Cyan
Set-Location $ProjectRoot
python -m src.main
