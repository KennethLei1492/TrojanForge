# TrojanForge - 24/7 self-correcting Hide/Hunt/Fix co-training launcher (Windows).
#
#   .\run_training.ps1                 # default 2000-step run
#   .\run_training.ps1 -Hours 24       # run 24/7 for a day
#   .\run_training.ps1 -Forever        # run until you stop it (Ctrl-C)
#   .\run_training.ps1 -Once           # one Hide/Hunt/Fix episode, print the row
#   .\run_training.ps1 -RealVerifyEvery 200   # audit with real iverilog
#
param(
    [int]$Steps = 2000,
    [double]$Hours = 0,
    [switch]$Forever,
    [switch]$Once,
    [int]$RealVerifyEvery = 0,
    [string]$RunDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$argsList = @()
if ($Once)            { $argsList += "--once" }
elseif ($Forever)     { $argsList += "--forever" }
elseif ($Hours -gt 0) { $argsList += @("--hours", $Hours) }
else                  { $argsList += @("--steps", $Steps) }
if ($RealVerifyEvery -gt 0) { $argsList += @("--real-verify-every", $RealVerifyEvery) }
if ($RunDir -ne "")         { $argsList += @("--run-dir", $RunDir) }

Write-Host "Launching TrojanForge: python -m trojan_forge $($argsList -join ' ')"
python -m trojan_forge @argsList
