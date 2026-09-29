$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if ($env:OS -ne "Windows_NT") { throw "当前版本只支持 Windows。" }
$pythonCommand = if ($env:DOUYIN_AUDIT_PYTHON) {
    $env:DOUYIN_AUDIT_PYTHON
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    (Get-Command py).Source
} else {
    throw "未找到 Python。请安装 Python 3.10 或更高版本，并加入 PATH。"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "未找到 Node.js 20+。" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "未找到 npm；它通常随 Node.js 一起安装。" }

$pythonVersion = & $pythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.10") { throw "需要 Python 3.10+，当前为 $pythonVersion。" }
$nodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -lt 20) { throw "需要 Node.js 20+，当前为 $(node --version)。" }

$edgeCandidates = @(
    $env:DOUYIN_AUDIT_EDGE,
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { $_ }
if (-not ($edgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)) {
    throw "未找到 Microsoft Edge。可通过 DOUYIN_AUDIT_EDGE 指定 msedge.exe。"
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $pythonCommand -m venv .venv
}
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"
npm install --no-fund --no-audit --cache .npm-cache
npm run check
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
Write-Host "初始化完成。运行 .\run.ps1 --items 3 开始少量测试。"
