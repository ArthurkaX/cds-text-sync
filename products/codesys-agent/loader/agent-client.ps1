# Developer client for the cts agent pipe. Sends one request line and prints the reply;
# with -Listen N it subscribes to events first and prints everything for N seconds.
#
#   .\agent-client.ps1 -Method hello
#   .\agent-client.ps1 -Method state
#   .\agent-client.ps1 -Method ping -AgentPid 1234
#   .\agent-client.ps1 -Listen 60 -Events 'online.*'
param(
    [string]$Method = "hello",
    [string]$Params = "{}",
    [int]$AgentPid = 0,
    [int]$Listen = 0,
    [string]$Events = "*"
)

if ($AgentPid -eq 0) {
    $names = [System.IO.Directory]::GetFiles("\\.\pipe\") | Where-Object { $_ -like "*cts-agent-*" }
    if (-not $names) { Write-Error "no cts-agent pipe found"; exit 2 }
    $pipe = ($names | Select-Object -First 1) -replace '^.*\\', ''
} else {
    $pipe = "cts-agent-$AgentPid"
}

$c = New-Object System.IO.Pipes.NamedPipeClientStream(".", $pipe, [System.IO.Pipes.PipeDirection]::InOut)
$c.Connect(3000)
$enc = New-Object System.Text.UTF8Encoding($false)
$w = New-Object System.IO.StreamWriter($c, $enc); $w.AutoFlush = $true; $w.NewLine = "`n"
$r = New-Object System.IO.StreamReader($c, $enc)

function Send($line) { $w.WriteLine($line) }

"pipe: $pipe"
$sw = [Diagnostics.Stopwatch]::StartNew()
if ($Listen -gt 0) {
    Send ('{"id":"sub","method":"subscribe","params":{"events":["' + $Events + '"]}}')
    $r.ReadLine()
    $deadline = (Get-Date).AddSeconds($Listen)
    $task = $r.ReadLineAsync()
    while ((Get-Date) -lt $deadline) {
        if ($task.Wait(500)) {
            if ($null -eq $task.Result) { "disconnected"; break }
            $task.Result
            $task = $r.ReadLineAsync()
        }
    }
} else {
    Send ('{"id":"1","method":"' + $Method + '","params":' + $Params + '}')
    $r.ReadLine()
    "(round trip $($sw.ElapsedMilliseconds) ms)"
}
$c.Dispose()
