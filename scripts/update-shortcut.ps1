#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ConfigPath,
    [string]$ShortcutPath
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Windows 10/11 is required.' }
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$python = Join-Path $root '.venv/Scripts/python.exe'
$pythonw = Join-Path $root '.venv/Scripts/pythonw.exe'
$icon = Join-Path $root 'wq_panel/assets/app.ico'
foreach ($required in @($python, $pythonw, $icon, (Join-Path $root 'wq_panel/assets/app.png'), (Join-Path $root 'wq_panel/assets/app.svg'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw 'Panel runtime or icon assets are missing; run scripts/install.ps1 first.' }
}
if (-not $ShortcutPath) {
    $ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WeChat QQ AI Panel.lnk'
}
$ShortcutPath = [IO.Path]::GetFullPath($ShortcutPath)
if ([IO.Path]::GetExtension($ShortcutPath) -ine '.lnk') { throw 'ShortcutPath must name a .lnk file.' }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
if (-not $ConfigPath -and $shortcut.Arguments) {
    # Preserve the installed account/deployment choice when refreshing an icon.
    if ($shortcut.Arguments -match '(?:^|\s)--access-config\s+(?:"([^"]+)"|(\S+))(?=\s|$)') {
        $ConfigPath = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
    } elseif ($shortcut.Arguments -match '(?:^|\s)--access-config(?:\s|$|=)') {
        throw 'Existing shortcut has an unrecognized --access-config value; supply -ConfigPath explicitly.'
    }
}
if (-not $ConfigPath) {
    $pointer = Join-Path $env:LOCALAPPDATA 'WeChatQQAIPanel/access-config.json'
    $regular = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local/share/wechat-qq-access/deployment.json'
    $legacy = Join-Path $env:LOCALAPPDATA 'MessagingAccess/deployment.json'
    $ConfigPath = if ($env:MESSAGING_ACCESS_CONFIG) { $env:MESSAGING_ACCESS_CONFIG }
        elseif (Test-Path -LiteralPath $pointer) { (Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json).configPath }
        elseif (Test-Path -LiteralPath $regular) { $regular }
        else { $legacy }
}
if (-not $ConfigPath -or -not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'The selected access configuration does not exist; supply -ConfigPath.' }
# Resolve MSIX/AppData namespaces through the same interpreter used at runtime.
$canonicalConfig = & $python -I -X utf8 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' $ConfigPath
if ($LASTEXITCODE -ne 0 -or -not [IO.Path]::IsPathFullyQualified($canonicalConfig)) { throw 'Cannot resolve the installed access configuration.' }
$ConfigPath = $canonicalConfig.Trim()
$deployment = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($deployment.schemaVersion -ne 1 -or -not (Test-Path -LiteralPath (Join-Path $deployment.projectRoot 'scripts/access.py') -PathType Leaf)) {
    throw 'A current wechat-qq-access deployment is required.'
}
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m wq_panel --access-config "' + $ConfigPath + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'WeChat / QQ AI message panel with conversation permissions'
$shortcut.IconLocation = $icon + ',0'
$shortcut.Save()
# A matching shortcut/process AppUserModelID prevents the taskbar using Python's identity.
# pywin32 is already part of requirements.lock; no dependency installation or launch occurs.
$setIdentity = @'
import sys
from win32com.propsys import propsys, pscon
from win32com.shell import shellcon
store = propsys.SHGetPropertyStoreFromParsingName(sys.argv[1], None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType("WeChatQQAI.Panel"))
store.Commit()
'@
& $python -I -X utf8 -c $setIdentity $ShortcutPath
if ($LASTEXITCODE -ne 0) { throw 'The shortcut icon was saved, but its Windows application identity could not be updated.' }
[pscustomobject]@{ shortcutUpdated = $true; configPinned = $true; launched = $false; dependenciesInstalled = $false }
