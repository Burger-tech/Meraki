# Turns the Windows hypervisor, virtualization-based security and Memory integrity (HVCI) off at the next
# restart. Run elevated (it relaunches itself with a UAC prompt). Old values are written to
# C:\Meraki\.local\hypervisor-change.log so tools\enable_hypervisor.ps1 can put them back.
$log = 'C:\Meraki\.local\hypervisor-change.log'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`""
    return
}
function Say($m) { ("{0}  {1}" -f (Get-Date -Format s), $m) | Tee-Object -FilePath $log -Append }
Say '=== before ==='
Say ((bcdedit /enum '{current}' | Select-String 'hypervisorlaunchtype') -join ' ')
$dg = 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard'
$hv = "$dg\Scenarios\HypervisorEnforcedCodeIntegrity"
Say ("EnableVirtualizationBasedSecurity = " + (Get-ItemProperty $dg -Name EnableVirtualizationBasedSecurity -ErrorAction SilentlyContinue).EnableVirtualizationBasedSecurity)
Say ("HVCI Enabled = " + (Get-ItemProperty $hv -Name Enabled -ErrorAction SilentlyContinue).Enabled)
bcdedit /set hypervisorlaunchtype off | ForEach-Object { Say $_ }
if (Test-Path $dg) { Set-ItemProperty $dg -Name EnableVirtualizationBasedSecurity -Value 0 -Type DWord -Force }
if (Test-Path $hv) { Set-ItemProperty $hv -Name Enabled -Value 0 -Type DWord -Force }
Say '=== after (takes effect at restart) ==='
Say ((bcdedit /enum '{current}' | Select-String 'hypervisorlaunchtype') -join ' ')
Say ("EnableVirtualizationBasedSecurity = " + (Get-ItemProperty $dg -Name EnableVirtualizationBasedSecurity -ErrorAction SilentlyContinue).EnableVirtualizationBasedSecurity)
Say ("HVCI Enabled = " + (Get-ItemProperty $hv -Name Enabled -ErrorAction SilentlyContinue).Enabled)
Say 'Restart Windows to apply. To undo: powershell -File C:\Meraki\tools\enable_hypervisor.ps1 (elevated), then restart.'
