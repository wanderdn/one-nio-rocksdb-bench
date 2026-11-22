param([switch]$Resume)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/run.ps1" -Image 'one-nio-rocks-bench:nocache' -SkipBuild -SkipPrepare -FunctionsOnly
$resultDir=Join-Path $PSScriptRoot 'results/nocache'
New-Item -ItemType Directory -Force $resultDir | Out-Null
foreach($case in @(@('nocache-multi','multi','nocache-rw-async'),@('nocache-get','get','nocache-rw'))) {
    $path=Join-Path $resultDir "$($case[0]).log"
    if($Resume -and (Test-Path $path) -and (Get-Content $path | Select-String '^RESULT ')) { continue }
    $null=Invoke-Bench $case[0] $case[1] 'uniform' $case[2] 1000 200 $true '/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2' '1g' 805306368
}
