# Reproducing this study

The current experiment and measurements are described in Russian in [METHOD.md](METHOD.md), [RESULTS.md](RESULTS.md) and [NOCACHE.md](NOCACHE.md).

Use Linux Docker containers with cgroup v2. All measured containers are pinned to logical CPU 2 and capped at 1 GiB total RAM, with swap disabled. Change CPU affinity in run.ps1 if CPU 2 is not available, and document the change. The databases are stored in a named Linux volume, not an NTFS bind mount. Dataset creation requires extra disk space and a 12 GiB initialization limit; initialization is excluded from timing.

```powershell
docker build -t one-nio-rocks-bench:1 .
docker build -f Dockerfile.uring -t one-nio-rocks-bench:equal .
docker volume create one-nio-rocks-bench-data-20261121
docker run --rm --memory=12g --memory-swap=12g --mount type=volume,src=one-nio-rocks-bench-data-20261121,dst=/data one-nio-rocks-bench:equal prepare /data 4294967296 4096
./run-equal.ps1
docker build -f Dockerfile.uring -t one-nio-rocks-bench:nocache .
./run-nocache.ps1
./run-nocache-no-uring.ps1
python analyze.py --suite equal
python report-equal.py
python analyze.py --suite nocache
python report-nocache.py
```

Skip dataset creation when the volume already exists. Do not run the suites concurrently against the same volume. Reports use the raw local Docker measurement snapshots after a new run, or the reduced public `*.resources.json` manifests included with the published data. Full Docker snapshots remain local and are excluded from Git.

**Security:** the experimental runner uses `seccomp=unconfined` to expose io_uring. This disables the container seccomp filter and is not a recommended production deployment. The native library is compiled with `PORTABLE=0` and should be rebuilt on another CPU. Tokens and device records are synthetic. No FCM network requests are performed.

All published results are one full run per configuration on one WSL2/VHDX host. They do not establish a universal ordering between libraries, or statistical significance for small differences. Historical unequal-resource experiments are excluded from the public comparison.
Прогон на 4 CPU и 4 потоках описан в [PARALLEL4.md](PARALLEL4.md).
