param(
    [string]$Image = 'one-nio-rocks-bench:uring',
    [string]$Volume = 'one-nio-rocks-bench-data-20261121',
    [int]$Passes = 20000,
    [int]$Warmup = 2000,
    [switch]$SkipPrepare,
    [switch]$SkipBuild,
    [switch]$ResumePilots,
    [string]$CpuSet = "2", [int]$Threads = 1, [int]$MultiSize = 5000, [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$resultDir = Join-Path $PSScriptRoot 'results'
New-Item -ItemType Directory -Force $resultDir | Out-Null
function Check-Exit([string]$Action) { if ($LASTEXITCODE -ne 0) { throw "$Action failed: $LASTEXITCODE" } }
if (!$SkipBuild) {
    docker build -t one-nio-rocks-bench:1 .; Check-Exit 'base build'
    if($Image -eq 'one-nio-rocks-bench:uring') { docker build -f Dockerfile.uring -t $Image .; Check-Exit 'native build' }
}
docker volume create $Volume | Out-Null
Check-Exit 'volume'
if (!$SkipPrepare) {
    docker run --rm --memory=12g --memory-swap=12g --mount "type=volume,src=$Volume,dst=/data" $Image prepare /data 4294967296 4096 2>&1 | Tee-Object (Join-Path $resultDir 'prepare.log')
    Check-Exit 'prepare'
}
function Invoke-Bench([string]$Label,[string]$Engine,[string]$Mode,[string]$Profile,[int]$Rounds,[int]$WarmRounds,[bool]$Stats=$false,[string]$Preload='/opt/rocks-native/uring_enable.so:/usr/lib/x86_64-linux-gnu/liburing.so.2',[string]$MemoryLimit='',[long]$NativeCacheBytes=1073741824) {
    $name = "onr-$Label"
    $logPath = Join-Path $resultDir "$Label.log"
    # Start large for one-nio's pointer relocation; lower before warmup or measurement.
    $statsValue = if($Stats) { '1' } else { '0' }
    docker run -d --name $name --memory=12g --memory-swap=12g --cpuset-cpus=$CpuSet -e "BENCH_THREADS=$Threads" -e "BENCH_MULTI_SIZE=$MultiSize" --security-opt seccomp=unconfined -e BENCH_GATE=/tmp/bench-go -e "BENCH_CACHE_BYTES=$NativeCacheBytes" -e "BENCH_STATS=$statsValue" -e "LD_PRELOAD=$Preload" --mount "type=volume,src=$Volume,dst=/data" $Image run /data $Engine $Mode $Profile $Rounds $WarmRounds | Out-Null
    Check-Exit "start $Label"
    $ready = $false
    while (!$ready) {
        $logs = docker logs $name 2>&1
        $ready = [bool]($logs | Select-String 'READY_FOR_MEMORY_LIMIT')
        $running = docker inspect --format '{{.State.Running}}' $name
        if ($running -ne 'true') { $logs | Set-Content $logPath; throw "$Label stopped before ready: $logs" }
        if (!$ready) { Start-Sleep -Seconds 2 }
    }
    # Strict file-cache upper bound of 1 GiB for mmap profiles; native caches total 1 GiB for direct profiles.
    $limit = if ($Engine -eq 'nio' -or $Profile.StartsWith('mmap')) { '1g' } else { '1536m' }
    if($MemoryLimit) { $limit=$MemoryLimit }
    docker update --memory=$limit --memory-swap=$limit $name | Out-Null
    Check-Exit "limit $Label"
    docker inspect $name | Set-Content (Join-Path $resultDir "$Label.measurement.container.json")
    docker exec $name touch /tmp/bench-go
    Check-Exit "release $Label"
    $lastProgress = ''
    $releasedClose = $false
    do {
        Start-Sleep -Seconds 5
        $logs = docker logs $name 2>&1
        $running = docker inspect --format '{{.State.Running}}' $name
        if($Engine -eq 'nio' -and $running -eq 'true' -and !$releasedClose -and ($logs | Select-String '^PROC measure-end schedstat ')) {
            # All timed metrics and final snapshots are already recorded. Default storeSchema scans every entry.
            docker update --memory=12g --memory-swap=12g $name | Out-Null
            Check-Exit "close limit $Label"
            docker exec $name dd if=/data/one-nio.map of=/dev/null bs=16M status=none
            $releasedClose = $true
        }
        $progress = $logs | Select-String 'PROGRESS|RESULT' | Select-Object -Last 1 | ForEach-Object { $_.ToString() }
        if ($progress -and $progress -ne $lastProgress) { Write-Host "$Label $progress"; $lastProgress=$progress }
        $running = docker inspect --format '{{.State.Running}}' $name
    } while ($running -eq 'true')
    docker logs $name 2>&1 | Set-Content $logPath
    $exitCode = docker inspect --format '{{.State.ExitCode}}' $name
    docker inspect $name | Set-Content (Join-Path $resultDir "$Label.container.json")
    if ($exitCode -ne '0') { throw "$Label failed: $exitCode. See $logPath" }
    $line = Get-Content $logPath | Select-String '^RESULT ' | Select-Object -Last 1
    if (!$line) { throw "No result: $Label" }
    $result = $line.ToString().Substring(7) | ConvertFrom-Json
    $metricsLine = Get-Content $logPath | Select-String '^METRICS ' | Select-Object -Last 1
    if($metricsLine) { $metrics = $metricsLine.ToString().Substring(8) | ConvertFrom-Json; foreach($prop in $metrics.PSObject.Properties) { $result | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value } }
    $result | Add-Member -NotePropertyName label -NotePropertyValue $Label
    $result | ConvertTo-Json -Compress | Add-Content (Join-Path $resultDir 'runs.jsonl')
    docker rm $name | Out-Null
    return $result
}

if($FunctionsOnly) { return }

throw 'Use run-equal.ps1, run-nocache.ps1 or run-nocache-no-uring.ps1. This file provides shared runner functions.'
