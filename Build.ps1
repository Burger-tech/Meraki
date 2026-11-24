param([ValidateSet('diag', 'release', 'both')][string]$Profile = 'diag')
$ErrorActionPreference = 'Stop'
$variables = 'CARGO_HOME', 'RUSTUP_HOME', 'CARGO_TARGET_DIR', 'TEMP', 'TMP', 'PATH', 'RUSTUP_TOOLCHAIN'
$previous = @{}
foreach ($name in $variables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name) }
Push-Location $PSScriptRoot
try {
    $manifest = Join-Path $PSScriptRoot 'baseline\Cargo.toml'
    if (!(Test-Path $manifest)) { throw 'Run git submodule update --init first.' }
    $local = Join-Path $PSScriptRoot '.local'
    $env:CARGO_HOME = Join-Path $local 'cargo'
    $env:RUSTUP_HOME = Join-Path $local 'rustup'
    $env:CARGO_TARGET_DIR = Join-Path $PSScriptRoot 'baseline\target'
    $env:TEMP = $env:TMP = Join-Path $local 'tmp'
    New-Item -ItemType Directory -Force $env:TEMP | Out-Null
    $env:PATH = "$(Join-Path $env:CARGO_HOME 'bin');$env:PATH"
    $pin = Select-String -Path baseline/rust-toolchain.toml -Pattern '^channel\s*=\s*"([^"]+)"$'
    $env:RUSTUP_TOOLCHAIN = $pin.Matches[0].Groups[1].Value
    if (!(Test-Path (Join-Path $env:RUSTUP_HOME "toolchains\$($env:RUSTUP_TOOLCHAIN)-x86_64-pc-windows-msvc\bin\rustc.exe"))) {
        rustup toolchain install $env:RUSTUP_TOOLCHAIN --profile minimal
        if ($LASTEXITCODE) { throw 'Rust toolchain setup failed.' }
    }
    foreach ($build in @('diag', 'release')) {
        if ($Profile -ne 'both' -and $build -ne $Profile) { continue }
        $options = @('--locked', '--manifest-path', $manifest, '-p', 'victory', '--profile', $build)
        if ($build -eq 'diag') { $options += '--features', 'diagnostics' }
        cargo build @options
        if ($LASTEXITCODE) { throw "Cargo build failed ($build)." }
    }
} finally {
    foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $previous[$name]) }
    Pop-Location
}
