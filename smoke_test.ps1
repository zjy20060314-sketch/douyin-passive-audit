$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$output = Join-Path $PSScriptRoot "data_live_debug\smoke_$stamp"
& "$PSScriptRoot\run.ps1" --items 3 --min-dwell-seconds 3 --max-dwell-seconds 15 --login-wait-seconds 300 --output $output
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\verify_output.py" $output --expected-items 3
exit $LASTEXITCODE
