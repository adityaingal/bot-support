param(
  [string]$Url = "https://discord-og-bot.onrender.com",
  [int]$TimeoutMin = 480,
  [int]$IntervalSec = 60
)

$deadline = (Get-Date).AddMinutes($TimeoutMin)
$last = ""

while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-RestMethod -Uri "$Url/api/status" -TimeoutSec 15 -ErrorAction Stop
    $d = $r.discord
    $line = "phase=$($d.phase) attempt=$($d.attempt) next_retry=$($d.next_retry_in_s)s connected=$($d.connected)"
    if ($line -ne $last) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $line"
      $last = $line
    }
    if ($d.connected) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Render is ONLINE - stopping local bot (handover)"
      Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like "*CodeX.py*" } |
        ForEach-Object {
          Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
          Write-Host "[$(Get-Date -Format 'HH:mm:ss')] stopped local PID $($_.ProcessId)"
        }
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] HANDOVER COMPLETE - Render now hosts the bot"
      exit 0
    }
  } catch {
    $m = $_.Exception.Message
    if ($m -ne $last) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] status unreachable: $m"
      $last = $m
    }
  }
  Start-Sleep -Seconds $IntervalSec
}

Write-Host "TIMEOUT after $TimeoutMin min - Render never connected; local bot left running."
exit 1
