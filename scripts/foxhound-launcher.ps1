param(
    [switch]$ConsoleMode,
    [string]$GameExe,
    [ValidateSet('release', 'diag')][string]$Build = 'release'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo "target\$Build\victory.exe"
$stateDir = Join-Path $env:LOCALAPPDATA 'Foxhound'
$statePath = Join-Path $stateDir 'launcher.json'

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath)) { return @{} }
    try { return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch { return @{} }
}

function Save-State([hashtable]$state) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Find-GameExe([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $null }
    if ((Test-Path -LiteralPath $path -PathType Leaf) -and (Split-Path $path -Leaf) -ieq 'game_scarlett_master.exe') {
        return (Resolve-Path -LiteralPath $path).Path
    }
    if (Test-Path -LiteralPath $path -PathType Container) {
        $candidate = Join-Path $path 'game_scarlett_master.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

function Start-Game([hashtable]$options) {
    if ($options.Console -notin 'series-x', 'series-s') { throw 'Select a console profile.' }
    $exe = Find-GameExe $options.GameExe
    if (-not $exe) { throw 'Select the folder or file that contains game_scarlett_master.exe.' }
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) { throw "The runtime was not found at $runtime. Build the release package first." }
    $repoPath = (Resolve-Path -LiteralPath $repo).Path.TrimEnd('\') + '\'
    if ($exe.StartsWith($repoPath, [StringComparison]::OrdinalIgnoreCase)) { throw 'The game must stay outside the Foxhound package folder.' }
    $gameDir = Split-Path -Parent $exe
    foreach ($archive in 'common.rpf', 'levels.rpf', 'audio.rpf') {
        if (-not (Test-Path -LiteralPath (Join-Path $gameDir $archive) -PathType Leaf)) {
            throw "Missing $archive beside the game executable. Select the executable in the complete game folder."
        }
    }

    $fsr = $options.Upscaler -eq 'fsr3'
    $ffxDir = $null
    if ($fsr) {
        if (-not $options.FfxDir -or -not (Test-Path -LiteralPath $options.FfxDir -PathType Container)) {
            throw 'Select the FidelityFX SDK signedbin folder, or choose the Native upscaler.'
        }
        $ffxDir = (Resolve-Path -LiteralPath $options.FfxDir).Path
        $required = @('amd_fidelityfx_loader_dx12.dll', 'amd_fidelityfx_upscaler_dx12.dll')
        if ($options.FrameGeneration) { $required += 'amd_fidelityfx_framegeneration_dx12.dll' }
        foreach ($dll in $required) {
            if (-not (Test-Path -LiteralPath (Join-Path $ffxDir $dll) -PathType Leaf)) {
                throw "Missing $dll in the FidelityFX SDK folder."
            }
        }
    }
    if (Get-Process victory -ErrorAction SilentlyContinue) { throw 'Close the running game before starting another session.' }

    $settings = @{
        VICTORY_NATIVE_1440P = if ($options.Console -eq 'series-x') { '1' } else { $null }
        VICTORY_FSR_FRAMEGEN = if ($fsr -and $options.FrameGeneration) { '1' } else { '0' }
        VICTORY_FSR_HUDLESS = if ($fsr -and $options.FrameGeneration -and $options.Hudless) { '1' } else { '0' }
        VICTORY_PACKED_LIGHT_LIMIT = if ($options.PackedLightLimit) { '1' } else { '0' }
        VICTORY_FFX_UPSCALER = if ($fsr) { 'fsr3' } else { $null }
        VICTORY_FFX_DIR = $ffxDir
        VICTORY_FSR_PATH = if ($fsr) { '1' } else { '0' }
        VICTORY_DLSS = '0'; VICTORY_FRAMEGEN = '0'; VICTORY_DLSS_MODE = 'performance'
        VICTORY_RELAY = '1'; VICTORY_RELAY_COPY = '1'; VICTORY_RELAY1_READ_WATERMARK = '1'
        VICTORY_RELAY1_CARD_FILLS = '1'; VICTORY_RELAY_COALESCE_FETCH = '1'
        VICTORY_PORT_CONSTANTS = '1'; VICTORY_MEMORY_CARD_MB = '1024'
        VICTORY_THIN = '1'; VICTORY_JOIN_PARTS = '8'; VICTORY_JOIN_COPIES = '1'
        VICTORY_CARD_REHASH_RUNS = '1'; VICTORY_CARD_STEPS = '1'; VICTORY_CARD_AWAKE = '1'
        VICTORY_WIDE_BACK = '1'; VICTORY_UPLOAD_AHEAD = '1'; VICTORY_MAP_THREADS = '1'; VICTORY_SHOW_AFTER = '1'
        VICTORY_SOFT_VIEWS = 'copies'; VICTORY_TEXTURE_POOL = '1'; VICTORY_TEXTURE_NO_WAIT = '1'
        VICTORY_TEXTURE_CATCHUP = '0'; VICTORY_LEVELS_ON_DEMAND = '0'; VICTORY_PRELUDE_UPLOADS = '1'
        VICTORY_SHOW_NEW_LATER = '1'; VICTORY_TABLED_REREAD = '1'; VICTORY_QUEUE_HOST_TEXTURES = '0'
        VICTORY_HEAP_SYNC_FIRST = '1'; VICTORY_SYNC_IN_PLACE = '1'; VICTORY_SPANS_QUICK = '1'
        VICTORY_SYNC_FINE = '1'; VICTORY_HEAP_SYNC_AT_SUBMIT = '1'; VICTORY_EARLY_DEPTH = '1'
        VICTORY_AMBIENT = 'constant:0.8'; VICTORY_AMBIENT_AIR = '0'; VICTORY_AMBIENT_SPECULAR = '0'
        VICTORY_LEAVE_OUT = '02384a60fda6f2d0,731a39171b568298'; VICTORY_PIPELINE_BOOK = '1'
        VICTORY_CARD_BUFFERS_MIN_KB = '64'; VICTORY_INDIRECT_WINDOW = '1'; VICTORY_INDIRECT_BATCH = '2'
        VICTORY_TEXTURE_STAGE_MS = '16'; VICTORY_POOL_SMALL = '0'; VICTORY_RIPE_BLOCKS = '0'
        VICTORY_KEEP_FREED = '0'; VICTORY_WINDOWS_BAR_MB = '2048'; VICTORY_PIPELINE_WORKERS = '3'
        VICTORY_PANEL = '1'
        VICTORY_LOG = 'warn,victory_gpu::ffx=info,victory_gpu::framegen=info'
    }
    Get-ChildItem Env:VICTORY_* -ErrorAction SilentlyContinue | Remove-Item
    foreach ($entry in $settings.GetEnumerator()) {
        if ($null -ne $entry.Value -and $entry.Value -ne '') { Set-Item "Env:$($entry.Key)" $entry.Value }
    }
    $env:VICTORY_GAME_DIR = Split-Path -Parent $exe
    $env:VICTORY_CACHE_DIR = Join-Path $stateDir 'cache'
    $env:VICTORY_DATA_DIR = Join-Path $stateDir 'data'
    New-Item -ItemType Directory -Force -Path $env:VICTORY_CACHE_DIR, $env:VICTORY_DATA_DIR | Out-Null
    $console = $options.Console
    $logDir = Join-Path $stateDir 'logs'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $log = Join-Path $logDir ('foxhound-{0:yyyyMMdd-HHmmss-fff}.log' -f (Get-Date))
    "game=$exe console=$console framegen=$($options.FrameGeneration) upscaler=$($options.Upscaler)" | Set-Content $log
    $stdout = "$log.out"; $stderr = "$log.err"
    $gameArgument = '"' + $exe + '"'
    Start-Process -FilePath $runtime -ArgumentList @('run', $gameArgument, '--console', $console, '--execute') -WorkingDirectory $repo -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    Save-State $options
    return $stderr
}

if ($ConsoleMode) {
    $state = Read-State
    $options = @{
        GameExe = if ($GameExe) { $GameExe } else { $state.GameExe }
        Console = if ($state.Console) { $state.Console } else { 'series-x' }
        FrameGeneration = if ($null -ne $state.FrameGeneration) { [bool]$state.FrameGeneration } else { $true }
        Hudless = if ($null -ne $state.Hudless) { [bool]$state.Hudless } else { $true }
        PackedLightLimit = if ($null -ne $state.PackedLightLimit) { [bool]$state.PackedLightLimit } else { $true }
        Upscaler = if ($state.Upscaler) { $state.Upscaler } else { 'native' }
        FfxDir = $state.FfxDir
    }
    $log = Start-Game $options
    Write-Host "Started Foxhound. Log: $log"
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$state = Read-State
$form = New-Object Windows.Forms.Form
$form.Text = 'Foxhound Launcher'; $form.ClientSize = New-Object Drawing.Size(630, 355); $form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
$font = New-Object Drawing.Font('Segoe UI', 9)
$form.Font = $font

function Add-Label([string]$text, [int]$x, [int]$y) { $label = New-Object Windows.Forms.Label; $label.Text=$text; $label.Left=$x; $label.Top=$y; $label.AutoSize=$true; $form.Controls.Add($label); return $label }
function Add-TextBox([int]$x, [int]$y, [int]$w) { $box = New-Object Windows.Forms.TextBox; $box.Left=$x; $box.Top=$y; $box.Width=$w; $form.Controls.Add($box); return $box }
Add-Label 'Select your legally obtained game executable' 20 18
$gameBox = Add-TextBox 20 42 500; $gameBox.Text = if ($state.GameExe) { $state.GameExe } else { '' }
$gameBrowse = New-Object Windows.Forms.Button; $gameBrowse.Text='Browse'; $gameBrowse.Left=530; $gameBrowse.Top=40; $gameBrowse.Width=80; $form.Controls.Add($gameBrowse)
$gameBrowse.Add_Click({ $dialog=New-Object Windows.Forms.OpenFileDialog; $dialog.Filter='Game executable|game_scarlett_master.exe'; if($dialog.ShowDialog() -eq 'OK'){$gameBox.Text=$dialog.FileName} })
Add-Label 'FSR SDK folder (optional, supplied separately)' 20 82
$ffxBox = Add-TextBox 20 106 500; $ffxBox.Text = if ($state.FfxDir) { $state.FfxDir } else { '' }
$ffxBrowse = New-Object Windows.Forms.Button; $ffxBrowse.Text='Browse'; $ffxBrowse.Left=530; $ffxBrowse.Top=104; $ffxBrowse.Width=80; $form.Controls.Add($ffxBrowse)
$ffxBrowse.Add_Click({ $dialog=New-Object Windows.Forms.FolderBrowserDialog; if($dialog.ShowDialog() -eq 'OK'){$ffxBox.Text=$dialog.SelectedPath} })
Add-Label 'Console profile' 20 150
$consoleBox=New-Object Windows.Forms.ComboBox; $consoleBox.Left=20; $consoleBox.Top=174; $consoleBox.Width=150; $consoleBox.DropDownStyle='DropDownList'; [void]$consoleBox.Items.AddRange(@('series-x','series-s')); $consoleBox.SelectedItem=if($state.Console){$state.Console}else{'series-x'}; $form.Controls.Add($consoleBox)
Add-Label 'Upscaler' 200 150
$upscaleBox=New-Object Windows.Forms.ComboBox; $upscaleBox.Left=200; $upscaleBox.Top=174; $upscaleBox.Width=150; $upscaleBox.DropDownStyle='DropDownList'; $upscaleBox.Items.AddRange(@('Native','FSR3')); $upscaleBox.SelectedItem=if($state.Upscaler -eq 'fsr3'){'FSR3'}else{'Native'}; $form.Controls.Add($upscaleBox)
$fg=New-Object Windows.Forms.CheckBox; $fg.Text='FSR Frame Generation'; $fg.Left=20; $fg.Top=220; $fg.Checked=if($null -ne $state.FrameGeneration){[bool]$state.FrameGeneration}else{$true}; $form.Controls.Add($fg)
$hud=New-Object Windows.Forms.CheckBox; $hud.Text='HUDless FSR input'; $hud.Left=220; $hud.Top=220; $hud.Checked=if($null -ne $state.Hudless){[bool]$state.Hudless}else{$true}; $form.Controls.Add($hud)
$light=New-Object Windows.Forms.CheckBox; $light.Text='Packed-light limiter'; $light.Left=390; $light.Top=220; $light.Checked=if($null -ne $state.PackedLightLimit){[bool]$state.PackedLightLimit}else{$true}; $form.Controls.Add($light)
$run=New-Object Windows.Forms.Button; $run.Text='Launch'; $run.Left=470; $run.Top=300; $run.Width=140; $run.Height=38; $form.Controls.Add($run)
$fg.AutoSize = $true
$hud.AutoSize = $true
$light.AutoSize = $true
$status=Add-Label 'Choose your game executable to begin.' 20 270
$logs = New-Object Windows.Forms.Button
$logs.Text = 'Open logs'
$logs.SetBounds(20, 300, 100, 38)
$form.Controls.Add($logs)
$logs.Add_Click({
    $folder = Join-Path $stateDir 'logs'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Invoke-Item -LiteralPath $folder
})
$form.AcceptButton = $run
$updateFsr = {
    $fg.Enabled = $upscaleBox.SelectedItem -eq 'FSR3'
    $hud.Enabled = $fg.Enabled -and $fg.Checked
}
$upscaleBox.Add_SelectedIndexChanged($updateFsr)
$fg.Add_CheckedChanged($updateFsr)
& $updateFsr
$run.Add_Click({
    try {
        $options = @{
            GameExe = $gameBox.Text
            FfxDir = $ffxBox.Text
            Console = $consoleBox.SelectedItem
            Upscaler = $upscaleBox.SelectedItem
            FrameGeneration = $fg.Checked
            Hudless = $hud.Checked
            PackedLightLimit = $light.Checked
        }
        $log = Start-Game $options
        $status.Text = "Started. Log: $(Split-Path $log -Leaf)"
    } catch {
        [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Foxhound Launcher', 'OK', 'Error')
    }
})
[void]$form.ShowDialog()
