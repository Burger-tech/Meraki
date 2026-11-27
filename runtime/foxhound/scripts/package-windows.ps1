param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$Runtime
)

$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$output = New-Item -ItemType Directory -Force -Path $OutputDirectory
$stage = Join-Path $output.FullName ('package-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $output.FullName 'Foxhound-Windows-x64.zip'
$launcher = Join-Path $output.FullName 'FoxhoundLauncher.exe'

New-Item -ItemType Directory -Force -Path "$stage\target\release", "$stage\scripts", "$stage\docs" | Out-Null
Copy-Item -LiteralPath $Runtime -Destination "$stage\target\release\victory.exe"
Copy-Item "$source\scripts\foxhound-launcher.ps1", "$source\scripts\play-foxhound.ps1" "$stage\scripts"
Copy-Item "$source\FoxhoundLauncher.cmd", "$source\README.md", "$source\LICENSE" $stage
Copy-Item "$source\docs\*.md" "$stage\docs"

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    "$stage\scripts\foxhound-launcher.ps1", [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors -join [Environment]::NewLine) }
& "$stage\target\release\victory.exe" --version
if ($LASTEXITCODE -ne 0) { throw 'Packaged runtime failed to start.' }
Compress-Archive -Path "$stage\*" -DestinationPath $zip -Force

$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$launcher" "/resource:$zip,Foxhound.Package" `
    /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll `
    (Join-Path $PSScriptRoot 'FoxhoundLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }

Get-FileHash -Algorithm SHA256 -LiteralPath $launcher, $zip | ForEach-Object {
    '{0}  {1}' -f $_.Hash, (Split-Path $_.Path -Leaf)
} | Set-Content -LiteralPath (Join-Path $output.FullName 'SHA256SUMS.txt') -Encoding ascii
