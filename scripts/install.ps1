#Requires -Version 7.0
[CmdletBinding()]
param([string]$PythonExe,
    [string]$ConfigPath = $(if ($env:MESSAGING_ACCESS_CONFIG) { $env:MESSAGING_ACCESS_CONFIG } else { Join-Path $env:LOCALAPPDATA 'MessagingAccess/deployment.json' }),
    [switch]$SkipShortcut)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Windows 10/11 is required.' }
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    $accessInstaller = Join-Path (Split-Path $root -Parent) 'access/scripts/install.ps1'
    if (-not (Test-Path -LiteralPath $accessInstaller)) { throw 'Clone wechat-qq-access into the sibling access directory first.' }
    $arguments = @{ ConfigPath = $ConfigPath }
    if ($PythonExe) { $arguments.PythonExe = $PythonExe }
    & $accessInstaller @arguments
}
$deployment = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($deployment.schemaVersion -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $deployment.projectRoot 'scripts/access.py'))) {
    throw 'A current wechat-qq-access deployment is required.'
}
if (-not $PythonExe) { $PythonExe = $deployment.pythonExe }
$version = & $PythonExe -c 'import sys; print("%d.%d" % sys.version_info[:2])'
if ($LASTEXITCODE -ne 0 -or $version -ne '3.11') { throw 'Select Python 3.11 with -PythonExe.' }
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if (Test-Path -LiteralPath $venv) { throw 'Incomplete panel .venv retained; inspect it before reinstalling.' }
    & $PythonExe -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Panel environment creation failed.' }
}
& $python -m pip install --disable-pip-version-check --index-url https://pypi.org/simple -r (Join-Path $root 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Panel dependency installation failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Panel dependencies are incompatible.' }
$private = Join-Path $env:LOCALAPPDATA 'WeChatQQAIPanel'
[void][IO.Directory]::CreateDirectory($private)
[IO.File]::WriteAllText((Join-Path $private 'access-config.json'),
    (@{configPath=[IO.Path]::GetFullPath($ConfigPath)} | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
if (-not $SkipShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'WeChat QQ AI Panel.lnk'))
    $shortcut.TargetPath = Join-Path $venv 'Scripts/pythonw.exe'
    $shortcut.Arguments = '-m wq_panel'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = 'WeChat / QQ AI message panel with conversation permissions'
    $shortcut.Save()
}
Write-Output ([pscustomobject]@{ installed = $true; accessReused = $true; modelCalled = $false })
