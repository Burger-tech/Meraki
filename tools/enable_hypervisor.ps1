# Undo of tools\disable_hypervisor.ps1: hypervisor on again, virtualization-based security and Memory
# integrity back on, effective at the next restart. Run elevated (relaunches itself with a UAC prompt).
$log = 'C:\Meraki\.local\hypervisor-change.log'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`""
    return
}
function Say($m) { ("{0}  {1}" -f (Get-Date -Format s), $m) | Tee-Object -FilePath $log -Append }
bcdedit /set hypervisorlaunchtype auto | ForEach-Object { Say $_ }
$dg = 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard'
$hv = "$dg\Scenarios\HypervisorEnforcedCodeIntegrity"
if (Test-Path $dg) { Set-ItemProperty $dg -Name EnableVirtualizationBasedSecurity -Value 1 -Type DWord -Force }
if (Test-Path $hv) { Set-ItemProperty $hv -Name Enabled -Value 1 -Type DWord -Force }
Say 'Hypervisor, VBS and Memory integrity set back on. Restart Windows to apply.'
