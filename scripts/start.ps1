#Requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$pythonw = Join-Path $root '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Run scripts/install.ps1 first.' }
Start-Process -FilePath $pythonw -ArgumentList '-m','wq_panel' -WorkingDirectory $root -WindowStyle Hidden
