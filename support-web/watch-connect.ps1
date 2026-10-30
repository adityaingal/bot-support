param(
  [string]$Url = "https://discord-og-bot.onrender.com",
  [int]$TimeoutMin = 90,
  [int]$IntervalSec = 15
)

$deadline = (Get-Date).AddMinutes($TimeoutMin)
$lastLine = ""

while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-RestMethod -Uri "$Url/api/status" -TimeoutSec 10 -ErrorAction Stop
    $d = $r.discord

    if ($d.connected) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] CONNECTED - bot online (attempts: $($d.attempt), last_error: $($d.last_error))"
      exit 0
    }

    $line = "phase=$($d.phase) attempt=$($d.attempt) next_retry=$($d.next_retry_in_s)s error=$($d.last_error) updated=$($d.updated)"
    if ($line -ne $lastLine) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $line"
      $lastLine = $line
    }

    if ($r.web.status -ne "online") {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] web service is '$($r.web.status)' - process may have crashed"
    }
  } catch {
    $msg = $_.Exception.Message
    if ($msg -ne $lastLine) {
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] status unreachable: $msg"
      $lastLine = $msg
    }
  }
  Start-Sleep -Seconds $IntervalSec
}

Write-Host "TIMEOUT after $TimeoutMin min - bot never connected. Check Render logs; do NOT restart the service."
exit 1
