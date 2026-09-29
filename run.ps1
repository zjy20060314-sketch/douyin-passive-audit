param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CollectorArgs
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$python = if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    Resolve-Path ".venv\Scripts\python.exe"
} else {
    if ($env:DOUYIN_AUDIT_PYTHON) { $env:DOUYIN_AUDIT_PYTHON }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { (Get-Command python).Source }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { (Get-Command py).Source }
    else { throw "未找到 Python 3.10+；请先运行 setup.ps1。" }
}
if (-not $CollectorArgs) { $CollectorArgs = @("--items", "3") }
& $python "live_douyin_pilot.py" @CollectorArgs
exit $LASTEXITCODE
