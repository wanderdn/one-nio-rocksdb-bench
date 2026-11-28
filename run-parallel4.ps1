param([switch]$Resume)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/run.ps1" -Image 'one-nio-rocks-bench:parallel4' -SkipBuild -SkipPrepare -FunctionsOnly -CpuSet "2-5" -Threads 4 -MultiSize 32
$resultDir=Join-Path $PSScriptRoot 'results/parallel4'
New-Item -ItemType Directory -Force $resultDir | Out-Null
foreach($case in @(
    @('parallel4-multi','multi','row-rw-async','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('parallel4-get','get','block-rw','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('parallel4-nio','nio','mmap','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
    @('parallel4-multi-no-uring','multi','row-rw-async','/usr/lib/x86_64-linux-gnu/liburing.so.2')
)) {
    $path=Join-Path $resultDir "$($case[0]).log"
    if($Resume -and (Test-Path $path) -and (Get-Content $path | Select-String '^RESULT ')) { continue }
    $null=Invoke-Bench $case[0] $case[1] 'uniform' $case[2] 1000 200 $true $case[3] '1g' 805306368
}
Write-Host 'PARALLEL4 SERIES COMPLETE'
