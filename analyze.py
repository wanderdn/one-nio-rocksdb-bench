"""Summarize measured intervals; never use startup memory peaks as measured RSS."""
import json
import re
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--suite', choices=('cold', 'hot', 'equal', 'nocache', 'parallel4', 'repeated4'), default='equal')
args = parser.parse_args()
RESULTS = ROOT / 'results' / (args.suite if args.suite != 'hot' else '')


def line(text, prefix):
    found = [s[len(prefix):] for s in text.splitlines() if s.startswith(prefix)]
    return found[-1] if found else ''


def counters(text):
    return {k: int(v) for k, v in re.findall(r'(\w+)\s+(\d+)(?:;|$)', text)}


def io_counters(text):
    total = {}
    for entry in text.split(';'):
        for k, v in re.findall(r'(\w+)=(\d+)', entry):
            total[k] = total.get(k, 0) + int(v)
    return total


def proc_status(text):
    return {k: int(v) for k, v in re.findall(r'(\w+):\s*(\d+)', text)}


def difference(end, start):
    return {k: v - start.get(k, 0) for k, v in end.items()}


rows = []
for path in sorted(RESULTS.glob('*.log')):
    if not path.stem.startswith(('full-', 'pilot-', 'uniform-', 'diagnostic-', 'cold-', 'equal-', 'nocache-', 'parallel4-', 'repeat-')):
        continue
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    raw = line(text, 'RESULT ')
    if not raw:
        continue
    r = json.loads(raw)
    r.update(json.loads(line(text, 'METRICS ') or '{}'))
    r['label'] = path.stem
    if args.suite in ('parallel4','repeated4'):
        r['cpuPctFourCores'] = r['cpuPctOneCore'] / 4
        r['requestMetrics'] = {k: float(v) for k,v in re.findall(r'(\w+)=([\d.]+)', line(text, 'REQUEST_METRICS '))}
    snapshots = {}
    for phase in ('measure-start', 'measure-end'):
        snapshots[phase] = {
            'memory': counters(line(text, f'STAT {phase} memory.stat ')),
            'cpu': counters(line(text, f'STAT {phase} cpu.stat ')),
            'io': io_counters(line(text, f'STAT {phase} io.stat ')),
            'process': proc_status(line(text, f'PROC {phase} status ')),
            'events': counters(line(text, f'STAT {phase} memory.events ')),
        }
    before, after = snapshots['measure-start'], snapshots['measure-end']
    r['intervalCpu'] = difference(after['cpu'], before['cpu'])
    r['intervalIo'] = difference(after['io'], before['io'])
    r['intervalFaults'] = {k: after['memory'].get(k, 0) - before['memory'].get(k, 0)
                           for k in ('pgfault', 'pgmajfault', 'workingset_refault_file', 'pgscan', 'pgsteal')}
    r['intervalContextSwitchesMainThread'] = {
        k: after['process'].get(k, 0) - before['process'].get(k, 0)
        for k in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches')}
    r['snapshots'] = snapshots
    for k, source in [('rssEndMiB', 'VmRSS'), ('rssAnonEndMiB', 'RssAnon'), ('rssFileEndMiB', 'RssFile')]:
        r[k] = after['process'].get(source, 0) / 1024
    r['fileCacheEndMiB'] = after['memory'].get('file', 0) / 2**20
    r['anonEndMiB'] = after['memory'].get('anon', 0) / 2**20
    r['readMiB'] = r['intervalIo'].get('rbytes', 0) / 2**20
    r['writeMiB'] = r['intervalIo'].get('wbytes', 0) / 2**20
    r['cpuUserSeconds'] = r['intervalCpu'].get('user_usec', 0) / 1e6
    r['cpuSystemSeconds'] = r['intervalCpu'].get('system_usec', 0) / 1e6
    r['blockDeviceReadIOPS'] = r['intervalIo'].get('rios', 0) / r['seconds']
    cache = dict((k, int(v)) for k, v in re.findall(r'(blockBytes|rowBytes)=(\d+)', line(text, 'CACHE measure-end ')))
    r['blockCacheEndMiB'] = cache.get('blockBytes', 0) / 2**20
    r['rowCacheEndMiB'] = cache.get('rowBytes', 0) / 2**20
    # Native statistics are gathered in separate diagnostics, not headline timings.
    t0 = dict((k, int(v)) for k, v in re.findall(r'(rocksdb\.[\w.]+) COUNT : (\d+)', line(text, 'TICKERS measure-start ')))
    t1 = dict((k, int(v)) for k, v in re.findall(r'(rocksdb\.[\w.]+) COUNT : (\d+)', line(text, 'TICKERS measure-end ')))
    if t1:
        r['nativeTickers'] = difference(t1, t0)
    rows.append(r)

main_labels = {'equal-get','equal-nio','equal-multi','equal-multi-no-uring'} if args.suite=='equal' else ({'cold-get', 'cold-nio', 'cold-multi', 'cold-multi-no-uring'} if args.suite == 'cold' else {'full-get', 'full-nio', 'full-multi'})
if args.suite=='nocache': main_labels={'nocache-get','nocache-multi','nocache-multi-no-uring'}
if args.suite=='parallel4': main_labels={'parallel4-get','parallel4-nio','parallel4-multi','parallel4-multi-no-uring'}
main = [r for r in rows if r['label'] in main_labels]
if len(main) >= 3:
    for count in {r['gets'] for r in main}:
        assert len({r['checksum'] for r in main if r['gets']==count}) == 1, 'Equal-length run checksums differ'
    assert all(r['gets'] == (5_000_000 if args.suite in ('equal','nocache','parallel4') else ((50_000_000 if r['label']=='cold-multi' else 5_000_000) if args.suite == 'cold' else 100_000_000)) for r in main), 'Incomplete full run'
for r in rows:
    events = r['snapshots']['measure-end']['events']
    assert events.get('oom_kill', 0) == 0, f"OOM in {r['label']}"
(RESULTS / 'summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

print('| Профиль | Время, с | GET/с | CPU, % | p50 пакета, мс | p95 | p99 | p99.9 |')
print('|---|---:|---:|---:|---:|---:|---:|---:|')
for r in main:
    print(f"| {r['label']} ({r['profile']}) | {r['seconds']:.3f} | {r['getsPerSecond']:,.0f} | {r['cpuPctOneCore']:.2f} | {r['batchP50Ms']:.3f} | {r['batchP95Ms']:.3f} | {r['batchP99Ms']:.3f} | {r['batchP999Ms']:.3f} |")
print('\n| Профиль | RSS в конце, МиБ | File cache, МиБ | CPU time, с | GC, мс | Чтение, МиБ | Major faults |')
print('|---|---:|---:|---:|---:|---:|---:|')
for r in main:
    print(f"| {r['label']} | {r['rssEndMiB']:.1f} | {r['fileCacheEndMiB']:.1f} | {r['cpuSeconds']:.2f} | {r['gcMillis']} | {r['readMiB']:.3f} | {r['intervalFaults']['pgmajfault']} |")
print('\nCompleted:', ', '.join(r['label'] for r in rows))
