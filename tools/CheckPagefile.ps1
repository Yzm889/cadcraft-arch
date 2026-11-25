param([switch]$Apply, [int]$InitialMB = 16384, [int]$MaximumMB = 32768)
$ErrorActionPreference = "Stop"

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$pf = Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"

"物理内存: {0:N1} GB，空闲: {1:N1} GB" -f ($os.TotalVisibleMemorySize/1MB), ($os.FreePhysicalMemory/1MB)
"提交额度: {0:N1} GB，可用: {1:N1} GB" -f ($os.TotalVirtualMemorySize/1MB), ($os.FreeVirtualMemory/1MB)
"页面文件自动管理: {0}" -f $cs.AutomaticManagedPagefile
if ($pf) {
  foreach ($p in $pf) {
    "页面文件: {0} 当前 {1} MB / 峰值 {2} MB" -f $p.Name, $p.AllocatedBaseSize, $p.PeakUsage
  }
} else {
  "页面文件: 未发现 Win32_PageFileUsage"
}
if ($disk) { "C: 空闲: {0:N1} GB" -f ($disk.FreeSpace/1GB) }

if (-not $Apply) {
  "只检查，不改系统。要改页面文件，加 -Apply（需管理员，改完必须重启）。"
  exit 0
}

$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "改页面文件需要管理员权限；请用管理员 PowerShell 重跑。" }
if (-not $disk -or $disk.FreeSpace/1GB -lt (($MaximumMB/1024) + 8)) {
  throw ("C: 剩余空间不足，至少需要 {0:N1} GB；不改页面文件。" -f (($MaximumMB/1024) + 8))
}

if ($cs.AutomaticManagedPagefile) {
  Set-CimInstance -InputObject $cs -Property @{AutomaticManagedPagefile = $false}
}
$existing = Get-CimInstance Win32_PageFileSetting -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'C:*' } | Select-Object -First 1
if ($existing) {
  Set-CimInstance -InputObject $existing -Property @{InitialSize = $InitialMB; MaximumSize = $MaximumMB}
} else {
  New-CimInstance -ClassName Win32_PageFileSetting -Property @{
    Name = "C:\pagefile.sys"; InitialSize = $InitialMB; MaximumSize = $MaximumMB
  } | Out-Null
}
"已把 C: 页面文件设为 {0}–{1} MB；必须重启后生效。" -f $InitialMB, $MaximumMB
exit 0
