import json, statistics as st
from pathlib import Path
root=Path(__file__).resolve().parent
folder=root/'results/repeated4'
plan=json.loads((folder/'plan.json').read_text(encoding='utf-8-sig'))
rows=json.loads((folder/'summary.json').read_text())
assert len(rows)==len(plan)==40
indexed={r['label']:r for r in rows}
for p in plan:
 r=indexed[p['label']]
 assert r['gets']==5000000 and r['checksum']==-8131224688047484273
 config=json.loads((folder/(p['label']+'.measurement.container.json')).read_text(encoding='utf-8-sig'))[0]
 host=config['HostConfig']
 assert host['Memory']==host['MemorySwap']==p['memoryGiB']*2**30
 assert host['CpusetCpus']=='2-5'
 env=dict(e.split('=',1) for e in config['Config']['Env'] if '=' in e)
 assert int(env['BENCH_CACHE_BYTES'])==p['cacheBytes']
 assert env['BENCH_THREADS']=='4' and env['BENCH_MULTI_SIZE']=='32'
 safe={'HostConfig':{k:host[k] for k in ('Memory','MemorySwap','CpusetCpus')},'Config':{'Image':config['Config']['Image'],'Env':[e for e in config['Config']['Env'] if e.startswith(('BENCH_','LD_PRELOAD='))]}}
 (folder/(p['label']+'.resources.json')).write_text(json.dumps(safe,indent=2)+'\n')
 r.update({k:p[k] for k in ('round','memoryGiB','api')})
report=(root/'REPEATED4.md').read_text(encoding='utf-8-sig').split('## Результаты')[0].rstrip()+'\n'
report+='\n## Результаты\n\nCPU 100% означает одно занятое ядро; максимум четырёх CPU — 400%. CV — выборочное стандартное отклонение GET/с, делённое на среднее. Перцентили ниже — медианы перцентилей отдельных прогонов, не перцентили объединённой выборки.\n\n'
report+='| API | Память, ГиБ | GET/с, медиана | min–max | CV, % | CPU, % (медиана) | Пакет p50 / p95 / p99, мс |\n|---|---:|---:|---:|---:|---:|---:|\n'
groups={}
for api in ('nio','get','multi','multi-no-uring'):
 for mem in (1,2):
  g=[r for r in rows if r['api']==api and r['memoryGiB']==mem]; assert len(g)==5
  groups[api,mem]=g
  speeds=[r['getsPerSecond'] for r in g]
  median=lambda k: st.median(r[k] for r in g)
  report+=f"| {api} | {mem} | {st.median(speeds):.0f} | {min(speeds):.0f}–{max(speeds):.0f} | {100*st.stdev(speeds)/st.mean(speeds):.2f} | {median('cpuPctOneCore'):.2f} | {median('batchP50Ms'):.3f} / {median('batchP95Ms'):.3f} / {median('batchP99Ms'):.3f} |\n"
report+='\n## Эффект увеличения памяти\n\nОтношение медиан throughput и диапазон отношений парных прогонов одного раунда:\n\n'
for api in ('nio','get','multi','multi-no-uring'):
 a=groups[api,1]; b=groups[api,2]
 ratio=st.median(r['getsPerSecond'] for r in b)/st.median(r['getsPerSecond'] for r in a)
 pairs=[next(r['getsPerSecond'] for r in b if r['round']==i)/next(r['getsPerSecond'] for r in a if r['round']==i) for i in range(1,6)]
 report+=f'- {api}: {ratio:.3f}×; парные отношения {min(pairs):.3f}–{max(pairs):.3f}×.\n'
report+='\n## Задержка API-запроса\n\nGet и one-nio: выборка 1/16, один ключ. MultiGet: каждый запрос до 32 ключей целиком, включая consume; делить перцентили на 32 нельзя.\n\n| API | Память, ГиБ | p50 / p95 / p99 / p99.9, мкс (медианы) |\n|---|---:|---:|\n'
for (api,mem),g in groups.items():
 vals=[st.median(r['requestMetrics'][k] for r in g) for k in ('p50Us','p95Us','p99Us','p999Us')]
 report+=f"| {api} | {mem} | "+' / '.join(f'{v:.3f}' for v in vals)+' |\n'
report+='\n## Ресурсы\n\nМедианы по пяти запускам; RSS и file cache — снимки в конце измерения.\n\n| API | ГиБ | CPU time, с | RSS, МиБ | File cache, МиБ | Чтение, МиБ | Major faults | GC, мс |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
for (api,mem),g in groups.items():
 vals=[st.median(r[k] for r in g) for k in ('cpuSeconds','rssEndMiB','fileCacheEndMiB','readMiB')]
 report+=f"| {api} | {mem} | "+' | '.join(f'{v:.2f}' for v in vals)+f" | {st.median(r['intervalFaults']['pgmajfault'] for r in g):.0f} | {st.median(r['gcMillis'] for r in g):.0f} |\n"
report+='\n## Каждый прогон\n\n| Раунд | API | ГиБ | GET/с | Время, с | CPU, % | p99 пакета, мс |\n|---|---|---:|---:|---:|---:|---:|\n'
for p in plan:
 r=indexed[p['label']]
 report+=f"| {p['round']} | {p['api']} | {p['memoryGiB']} | {r['getsPerSecond']:.0f} | {r['seconds']:.3f} | {r['cpuPctOneCore']:.2f} | {r['batchP99Ms']:.3f} |\n"
report+='\n## Воспроизведение\n\n```powershell\n./run-repeated4.ps1 -Resume\npython analyze.py --suite repeated4\npython report-repeated4.py\n```\n\nСтенд и ограничения интерпретации прежние: WSL2/NVMe, гостевой Direct I/O не исключает кеш хоста/накопителя; seccomp=unconfined только для стенда. Обычный RocksDB Get не использует io_uring.\n'
(root/'REPEATED4.md').write_text(report)
(folder/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
print(report)
