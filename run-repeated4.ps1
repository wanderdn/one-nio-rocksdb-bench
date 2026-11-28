param([switch]$Resume)
$ErrorActionPreference='Stop'
. "$PSScriptRoot/run.ps1" -Image 'one-nio-rocks-bench:parallel4' -SkipBuild -SkipPrepare -FunctionsOnly -CpuSet '2-5' -Threads 4 -MultiSize 32
$resultDir=Join-Path $PSScriptRoot 'results/repeated4'
New-Item -ItemType Directory -Force $resultDir | Out-Null
$cases=@(
 @('multi','multi','row-rw-async','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
 @('get','get','block-rw','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
 @('nio','nio','mmap','/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2'),
 @('multi-no-uring','multi','row-rw-async','/usr/lib/x86_64-linux-gnu/liburing.so.2')
)
$plan=@()
for($round=1;$round -le 5;$round++) {
 for($slot=0;$slot -lt 4;$slot++) {
  $case=$cases[($slot+$round-1)%4]
  $memories=if(($round+$slot)%2 -eq 1){@(1,2)}else{@(2,1)}
  foreach($memory in $memories) {
   $plan += [pscustomobject]@{label="repeat-r$round-m$memory-$($case[0])";round=$round;memoryGiB=$memory;engine=$case[1];api=$case[0];profile=$case[2];preload=$case[3];cacheBytes=[long]$memory*805306368;passes=1000;warmup=200;threads=4;multiSize=32;cpus='2-5'}
  }
 }
}
$plan | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $resultDir 'plan.json')
$done=0
foreach($item in $plan) {
 $path=Join-Path $resultDir "$($item.label).log"
 if($Resume -and (Test-Path $path) -and (Get-Content $path | Select-String '^RESULT ')) { $done++; continue }
 Write-Host "SERIES_START $($done+1)/40 $($item.label) $(Get-Date -Format o)"
 $result=Invoke-Bench $item.label $item.engine 'uniform' $item.profile 1000 200 $true $item.preload "$($item.memoryGiB)g" $item.cacheBytes
 if($result.gets -ne 5000000 -or $result.checksum -ne -8131224688047484273){throw "Invalid result: $($item.label)"}
 $done++
 Write-Host "SERIES_DONE $done/40 $($item.label) $(Get-Date -Format o)"
}
docker run --rm --entrypoint sh --mount "type=bind,src=$PSScriptRoot,dst=/report" -w /report one-nio-rocks-bench:parallel4 -c 'python3 analyze.py --suite repeated4 && python3 report-repeated4.py'
Check-Exit 'repeated report'
Write-Host 'REPEATED4 SERIES COMPLETE'
