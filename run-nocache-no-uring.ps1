$ErrorActionPreference='Stop'
. "$PSScriptRoot/run.ps1" -Image 'one-nio-rocks-bench:nocache' -SkipBuild -SkipPrepare -FunctionsOnly
$resultDir=Join-Path $PSScriptRoot 'results/nocache'
$null=Invoke-Bench 'nocache-multi-no-uring' 'multi' 'uniform' 'nocache-rw-async' 1000 200 $true '/usr/lib/x86_64-linux-gnu/liburing.so.2' '1g' 805306368
