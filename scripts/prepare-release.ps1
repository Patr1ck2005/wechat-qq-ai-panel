#Requires -Version 7.0
[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$files = [Collections.Generic.List[object]]::new()
function Select-Public([IO.FileInfo]$File) {
    if ($File.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked public files are not permitted.' }
    $relative = [IO.Path]::GetRelativePath($root, $File.FullName)
    $content = [IO.File]::ReadAllText($File.FullName)
    if ($content -match '(?i)[A-Z]:[/\\](Dev[/\\]|Users[/\\])' -or
        $content -match '(?im)(?:accessToken|master_key|api_key)\s*[=:]\s*["''][A-Za-z0-9_\-]{24,}["'']') {
        throw "Possible private artifact in public source: $relative"
    }
    $files.Add([pscustomobject]@{path=$relative; source=$File.FullName; bytes=$File.Length})
}
foreach($name in @('README.md','AGENTS.md','INTEGRATION.md','LICENSE','THIRD_PARTY.md','requirements.lock','start-panel.cmd')) {
    Select-Public (Get-Item -LiteralPath (Join-Path $root $name))
}
foreach($folder in @('wq_panel','panel_models','resources','scripts','tests','.github')) {
    $pending=[Collections.Generic.Stack[string]]::new(); $pending.Push((Join-Path $root $folder))
    while($pending.Count) {
        foreach($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked source directory is not permitted.' }
            if($entry.PSIsContainer) {
                if($entry.Name -notin @('__pycache__','.local','.venv')) {$pending.Push($entry.FullName)}
            } elseif($entry.Extension -in @('.py','.html','.mjs','.md','.ps1','.yml','.yaml')) {Select-Public $entry}
        }
    }
}
Select-Public (Get-Item -LiteralPath (Join-Path $root '.gitignore'))
if(-not $CheckOnly) {
    $destination=Join-Path $root ('.local/release-'+[guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($destination)
    foreach($file in $files) {
        $target=Join-Path $destination $file.path
        [void][IO.Directory]::CreateDirectory((Split-Path $target -Parent))
        [IO.File]::Copy($file.source,$target,$false)
        if((Get-FileHash -LiteralPath $target).Hash -ne (Get-FileHash -LiteralPath $file.source).Hash) {throw 'Release copy differs.'}
    }
}
[pscustomobject]@{status='public-source-check-passed';files=$files.Count;sourceBytes=($files | Measure-Object bytes -Sum).Sum;uploaded=$false}
