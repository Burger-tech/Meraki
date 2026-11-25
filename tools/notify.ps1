<#
.SYNOPSIS
Sends one short Meraki status notification to ntfy.

.DESCRIPTION
Publishes to https://ntfy.sh with the title "Meraki" and priority 4. The topic
is read only from $env:NTFY_TOPIC, so it never lands in tracked files, command
lines, or captured logs.

The body is one plain-language outcome line, a blank line, then up to three
short labelled lines: headline measurement, blocker, and next action. Use
-Context to say whether this is gameplay, loading, or offline work, and
-Measured to mark a number as measured rather than estimated.

.EXAMPLE
./tools/notify.ps1 -Context gameplay -Outcome 'Reached the first mission' `
    -Measurement '58 fps average over two minutes' -Measured `
    -Next 'Retrying the next mission'

.EXAMPLE
./tools/notify.ps1 -Context offline -Outcome 'Frame pacing exporter is ready' `
    -Blocker 'Needs a live capture to confirm' -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Outcome,

    [ValidateSet('gameplay', 'loading', 'offline')]
    [string]$Context,

    [string]$Measurement,
    [string]$Blocker,
    [string]$Next,

    [switch]$Measured,
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$contextLabels = @{
    gameplay = 'Gameplay'
    loading  = 'Loading'
    offline  = 'Offline work'
}

function Format-ShortLine {
    param([string]$Name, [string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    if ($Value -match '[\r\n]') {
        throw "$Name must fit on one line."
    }
    $line = $Value.Trim()
    if ($line.Length -gt 160) {
        throw "$Name is $($line.Length) characters; keep ntfy lines to 160 or fewer."
    }
    if ($line -match '\b(?=[0-9A-Fa-f]*[A-Fa-f])[0-9A-Fa-f]{16,}\b' -or $line -match '0x[0-9A-Fa-f]{4,}') {
        throw "$Name looks like a raw hash; describe the outcome in plain language instead."
    }
    if ($line -match '(^|\s)[A-Za-z]:\\' -or $line -match '\\\\\S*\\') {
        throw "$Name contains a file path; name the result, not its location."
    }
    return $line
}

$outcomeLine = Format-ShortLine 'Outcome' $Outcome
if (-not $outcomeLine) {
    throw 'Outcome must not be blank.'
}
if ($Context) {
    $outcomeLine = "$($contextLabels[$Context]): $outcomeLine"
}

$detailLines = New-Object System.Collections.Generic.List[string]
$measurementLine = Format-ShortLine 'Measurement' $Measurement
if ($measurementLine) {
    $measurementLabel = if ($Measured) { 'Measured' } else { 'Estimated' }
    $detailLines.Add("${measurementLabel}: $measurementLine")
}
$blockerLine = Format-ShortLine 'Blocker' $Blocker
if ($blockerLine) {
    $detailLines.Add("Blocked: $blockerLine")
}
$nextLine = Format-ShortLine 'Next' $Next
if ($nextLine) {
    $detailLines.Add("Next: $nextLine")
}

$bodyLines = New-Object System.Collections.Generic.List[string]
$bodyLines.Add($outcomeLine)
if ($detailLines.Count -gt 0) {
    $bodyLines.Add('')
    foreach ($detail in $detailLines) { $bodyLines.Add($detail) }
}
$body = $bodyLines -join "`n"

if ($DryRun) {
    $topicState = if ([string]::IsNullOrWhiteSpace($env:NTFY_TOPIC)) { 'not set' } else { 'set (value hidden)' }
    Write-Output 'DRY RUN - nothing was sent.'
    Write-Output 'Title: Meraki'
    Write-Output 'Priority: 4'
    Write-Output 'Endpoint: https://ntfy.sh/<redacted-topic>'
    Write-Output "Topic: $topicState"
    Write-Output '--- body ---'
    Write-Output $body
    return
}

$topicName = $env:NTFY_TOPIC
if ([string]::IsNullOrWhiteSpace($topicName)) {
    throw 'NTFY_TOPIC is not set. Export it in the shell; never pass or commit the topic value.'
}
if ($topicName -notmatch '^[A-Za-z0-9_-]{1,64}$') {
    throw 'NTFY_TOPIC is not a valid ntfy topic name.'
}

$request = @{
    UseBasicParsing = $true
    Method          = 'Post'
    Uri             = "https://ntfy.sh/$topicName"
    Headers         = @{ Title = 'Meraki'; Priority = '4' }
    ContentType     = 'text/plain; charset=utf-8'
    Body            = [Text.Encoding]::UTF8.GetBytes($body)
    TimeoutSec      = 15
}

try {
    Invoke-WebRequest @request | Out-Null
} catch {
    $status = ''
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
        $status = " (HTTP $([int]$_.Exception.Response.StatusCode))"
    }
    throw "ntfy push failed$status. Check the network and NTFY_TOPIC, then retry."
}
Write-Output 'Sent the Meraki notification.'