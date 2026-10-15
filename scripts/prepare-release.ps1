#Requires -Version 7.0
<#
.SYNOPSIS
Build an explicit public-source preview without Git initialization or upload.
.DESCRIPTION
Copies only maintained public source types into a new .local/release-* directory.
Local deployment state, downloaded programs and evidence are never selected.
#>
[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$required = @('README.md', 'AGENTS.md', '.gitignore', 'LICENSE', 'THIRD_PARTY.md',
    'INTEGRATION.md', 'WEB_ENTRY.md', 'requirements.lock', 'start-panel.cmd')
$selected = [Collections.Generic.List[object]]::new()
$assetBytes = [long]0
function Test-PublicAsset([IO.FileInfo]$File, [string]$Relative) {
    $isDocument = $Relative -cmatch '^docs/assets/(product-overview|interface-preview)\.(svg|png)$'
    $isIcon = $Relative -cmatch '^wq_panel/assets/app\.(svg|png|ico)$'
    if (-not ($isDocument -or $isIcon)) { throw "Unapproved public asset path: $Relative" }
    $limit = switch ($File.Extension.ToLowerInvariant()) { '.svg' { 512KB }; '.png' { 4MB }; '.ico' { 1MB } }
    if ($File.Length -le 0 -or $File.Length -gt $limit) { throw "Public asset size is outside its limit: $Relative" }
    $script:assetBytes += $File.Length
    if ($script:assetBytes -gt 16MB) { throw 'Public assets exceed the 16 MiB total limit.' }
    if ($File.Extension -eq '.svg') {
        $svg = [IO.File]::ReadAllText($File.FullName)
        $settings = [Xml.XmlReaderSettings]::new()
        $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $reader = [Xml.XmlReader]::Create([IO.StringReader]::new($svg), $settings)
        $document = [Xml.XmlDocument]::new(); $document.XmlResolver = $null
        try { $document.Load($reader) } finally { $reader.Dispose() }
        if ($document.DocumentElement.LocalName -cne 'svg' -or $document.DocumentElement.NamespaceURI -cne 'http://www.w3.org/2000/svg') {
            throw "Invalid SVG document: $Relative"
        }
        foreach ($node in $document.SelectNodes('//*')) {
            if ($node.LocalName -match '^(script|foreignObject|iframe|object|embed)$') { throw "Active SVG content is forbidden: $Relative" }
            foreach ($attribute in $node.Attributes) {
                if ($attribute.LocalName -match '^on' -or ($attribute.LocalName -eq 'href' -and $attribute.Value -notmatch '^#[A-Za-z_][\w:.-]*$')) {
                    throw "Active or external SVG reference is forbidden: $Relative"
                }
            }
        }
        if ($svg -match '(?i)@import' -or $svg -match '<\?(?!xml\s)') {
            throw "External SVG resources are forbidden: $Relative"
        }
        foreach ($reference in [regex]::Matches($svg, '(?i)url\((?<target>[^)]*)\)')) {
            if ($reference.Groups['target'].Value.Trim().Trim([char[]]@('"', "'")) -notmatch '^#[A-Za-z_][\w:.-]*$') {
                throw "External SVG resources are forbidden: $Relative"
            }
        }
        return $svg
    }
    # Binary assets are checked as bytes, never decoded as public-source text.
    $data = [IO.File]::ReadAllBytes($File.FullName)
    if ($File.Extension -eq '.png') {
        if ($data.Length -lt 33 -or [Convert]::ToHexString($data[0..7]) -cne '89504E470D0A1A0A' -or
            [Text.Encoding]::ASCII.GetString($data, 12, 4) -cne 'IHDR') { throw "Invalid PNG asset: $Relative" }
        $width = [uint32]$data[16] * 16777216 + [uint32]$data[17] * 65536 + [uint32]$data[18] * 256 + [uint32]$data[19]
        $height = [uint32]$data[20] * 16777216 + [uint32]$data[21] * 65536 + [uint32]$data[22] * 256 + [uint32]$data[23]
        if ($width -lt 1 -or $height -lt 1 -or $width -gt 4096 -or $height -gt 4096) { throw "PNG dimensions exceed the public limit: $Relative" }
    } else {
        if ($data.Length -lt 22 -or [BitConverter]::ToUInt16($data, 0) -ne 0 -or [BitConverter]::ToUInt16($data, 2) -ne 1) {
            throw "Invalid ICO asset: $Relative"
        }
        $count = [BitConverter]::ToUInt16($data, 4)
        if ($count -lt 1 -or $count -gt 16 -or $data.Length -lt (6 + 16 * $count)) { throw "Invalid ICO directory: $Relative" }
        for ($index = 0; $index -lt $count; $index++) {
            $size = [BitConverter]::ToUInt32($data, 6 + 16 * $index + 8)
            $offset = [BitConverter]::ToUInt32($data, 6 + 16 * $index + 12)
            if ($size -lt 1 -or $offset -lt (6 + 16 * $count) -or ([long]$offset + $size) -gt $data.Length) { throw "Invalid ICO image bounds: $Relative" }
        }
    }
    return $null
}
function Test-ReadmeImages {
    $readme = [IO.File]::ReadAllText((Join-Path $root 'README.md'))
    $references = [Collections.Generic.List[string]]::new()
    foreach ($match in [regex]::Matches($readme, '!\[[^\]]*\]\(\s*(?:<(?<angle>[^>]+)>|(?<plain>[^\s\)]+))(?:\s+[^\)]*)?\)')) {
        $references.Add($(if ($match.Groups['angle'].Success) { $match.Groups['angle'].Value } else { $match.Groups['plain'].Value }))
    }
    foreach ($match in [regex]::Matches($readme, '(?is)<img\b[^>]*\bsrc\s*=\s*["''](?<source>[^"'']+)["'']')) { $references.Add($match.Groups['source'].Value) }
    foreach ($reference in $references) {
        if ($reference -match '^https?://') { continue }
        $path = [Uri]::UnescapeDataString(($reference -split '[?#]', 2)[0]).Replace('\', '/')
        if (-not $path -or $path -match '^[/\\]|^[A-Za-z][\w+.-]*:' -or $path -match '(^|/)\.\.(/|$)') { throw 'Unsafe local README image reference.' }
        $relative = [IO.Path]::GetRelativePath($root, [IO.Path]::GetFullPath((Join-Path $root $path))).Replace('\', '/')
        if ($relative -cnotin @($selected.path)) { throw "README image is absent from public selection: $relative" }
    }
}
function Add-PublicFile([IO.FileInfo]$File) {
    if (($File.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Public source must not be a file link.' }
    $relative = [IO.Path]::GetRelativePath($root, $File.FullName).Replace('\', '/')
    if ($relative.StartsWith('../') -or $relative -match '(^|/)(vendor|\.venv|\.local|evidence|node_modules|__pycache__)(/|$)') {
        throw 'A private or external path entered the public file selection.'
    }
    $text = if ($File.Extension -in @('.svg', '.png', '.ico')) { Test-PublicAsset $File $relative } else { [IO.File]::ReadAllText($File.FullName) }
    if ($text -match '(?i)[A-Z]:[/\\](Dev[/\\]|Users[/\\])') {
        throw "Machine-specific path found in public source: $relative"
    }
    if ($text -match '(?im)(?:accessToken|master_key|api_key)\s*[=:]\s*["''][A-Za-z0-9_\-]{24,}["'']') {
        throw "Possible literal credential found in public source: $relative"
    }
    $selected.Add([pscustomobject]@{ path = $relative; bytes = $File.Length;
        sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); source = $File.FullName })
}
foreach ($name in $required) {
    $path = Join-Path $root $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required public file: $name" }
    Add-PublicFile (Get-Item -LiteralPath $path)
}
$types = @{ docs = @('.md', '.svg', '.png'); scripts = @('.ps1', '.py'); tests = @('.ps1', '.py');
    wq_panel = @('.py', '.html', '.svg', '.png', '.ico'); panel_models = @('.py');
    resources = @('.md', '.mjs'); '.github' = @('.yaml', '.yml') }
foreach ($directory in $types.Keys) {
    $base = Join-Path $root $directory
    if (-not (Test-Path -LiteralPath $base)) { continue }
    if (((Get-Item -LiteralPath $base).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Linked public source directory $directory is not publishable."
    }
    $pending = [Collections.Generic.Stack[string]]::new(); $pending.Push($base)
    while ($pending.Count -gt 0) {
        foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Linked source path under $directory is not publishable." }
            if ($entry.PSIsContainer) {
                if ($entry.Name -notin @('__pycache__', '.local', '.venv', 'node_modules')) { $pending.Push($entry.FullName) }
            } elseif ($entry.Extension.ToLowerInvariant() -in $types[$directory]) { Add-PublicFile $entry }
        }
    }
}
Test-ReadmeImages
$files = @($selected | Sort-Object path)
$manifestFiles = @($files | Select-Object path, bytes, sha256)
$bytes = [long]0; foreach ($file in $files) { $bytes += $file.bytes }
if (-not $CheckOnly) {
    $parent = Join-Path $root '.local'
    if ((Test-Path -LiteralPath $parent) -and ((Get-Item -LiteralPath $parent).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The private preview parent must not be a link.'
    }
    [void][IO.Directory]::CreateDirectory($parent)
    $destination = Join-Path $parent ('release-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [void][IO.Directory]::CreateDirectory($destination)
    foreach ($file in $files) {
        $target = Join-Path $destination $file.path
        [void][IO.Directory]::CreateDirectory((Split-Path $target -Parent))
        [IO.File]::Copy($file.source, $target, $false)
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ine $file.sha256) { throw 'Copied public source hash differs.' }
    }
    $manifest = [ordered]@{ schemaVersion = 1; files = $manifestFiles; sourceBytes = $bytes }
    [IO.File]::WriteAllText((Join-Path $destination 'release-manifest.json'), ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    Write-Output ([pscustomobject]@{ status = 'public-preview-created'; directory = $destination; files = $files.Count; sourceBytes = $bytes; uploaded = $false })
} else {
    Write-Output ([pscustomobject]@{ status = 'public-source-check-passed'; files = $files.Count; sourceBytes = $bytes; uploaded = $false })
}
