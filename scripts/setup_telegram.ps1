# Connects the Telegram bot to the GitHub repo without the token ever appearing on screen or in a file.
# Before running: create the bot with @BotFather and send it any message from your own Telegram account.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup_telegram.ps1
$ErrorActionPreference = 'Stop'
$repo = 'doric2000/job-radar'

$secure = Read-Host 'Paste the bot token from BotFather' -AsSecureString
$token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

$me = Invoke-RestMethod "https://api.telegram.org/bot$token/getMe"
Write-Host "Bot: @$($me.result.username)"

$updates = Invoke-RestMethod "https://api.telegram.org/bot$token/getUpdates"
$chat = $updates.result | ForEach-Object { $_.message.chat } | Where-Object { $_ } | Select-Object -Last 1
if (-not $chat) { throw "No messages found. Send any message to @$($me.result.username) in Telegram, then run this again." }
Write-Host "Chat: $($chat.id) ($($chat.first_name) $($chat.username))"

$token | gh secret set TELEGRAM_BOT_TOKEN -R $repo
"$($chat.id)" | gh secret set TELEGRAM_CHAT_ID -R $repo

$body = @{ chat_id = $chat.id; text = 'Job Radar connected. Alerts will arrive here.' }
Invoke-RestMethod "https://api.telegram.org/bot$token/sendMessage" -Method Post -Body $body | Out-Null
Write-Host 'Done: both secrets are set and a test message was sent.'
