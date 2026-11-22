param([switch]$Resume)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/run.ps1" -Image 'one-nio-rocks-bench:equal' -SkipBuild -SkipPrepare -FunctionsOnly
$resultDir=Join-Path $PSScriptRoot 'results/equal'
New-Item -ItemType Directory -Force $resultDir | Out-Null
foreach($case in @(
    @('equal-multi','multi','row-rw-async','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('equal-get','get','block-rw','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('equal-nio','nio','mmap','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('equal-multi-no-uring','multi','row-rw-async','/usr/lib/x86_64-linux-gnu/liburing.so.2')
)) {
    $path=Join-Path $resultDir "$($case[0]).log"
    if($Resume -and (Test-Path $path) -and (Get-Content $path | Select-String '^RESULT ')) { continue }
    $null=Invoke-Bench $case[0] $case[1] 'uniform' $case[2] 1000 200 $true $case[3] '1g' 805306368
}
Write-Host 'EQUAL SERIES COMPLETE'
