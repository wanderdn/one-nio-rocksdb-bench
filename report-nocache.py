import json
from pathlib import Path
p=Path(__file__).resolve().parent
rows=json.loads((p/'results/nocache/summary.json').read_text())
names={'nocache-get':'Get, Direct I/O','nocache-multi':'MultiGet, Direct I/O + io_uring','nocache-multi-no-uring':'MultiGet, Direct I/O, без io_uring'}
assert len(rows)==3 and len({r['checksum'] for r in rows})==1
for r in rows:
 manifest=p/f"results/nocache/{r['label']}.resources.json"
 if not manifest.exists(): manifest=p/f"results/nocache/{r['label']}.measurement.container.json"
 resource=json.loads(manifest.read_text(encoding='utf-8-sig'))
 c=resource[0] if isinstance(resource,list) else resource
 h=c['HostConfig'];assert h['Memory']==h['MemorySwap']==1073741824 and h['CpusetCpus']=='2'
 assert r['gets']==5000000 and r['blockCacheEndMiB']==r['rowCacheEndMiB']==0
 assert r['snapshots']['measure-end']['events'].get('oom',0)==0
 t=(p/f"results/nocache/{r['label']}.log").read_text(encoding='utf-8-sig')
 assert 'directReads=true noBlockCache=true rowCache=false fillCache=false' in t
 env=c['Config']['Env'];hook=any(x.startswith('LD_PRELOAD=') and 'uring_enable.so' in x for x in env)
 assert hook==(r['label']!='nocache-multi-no-uring')
s='''# RocksDB без кешей данных: Direct I/O

Дополнение к серии с равным RAM-бюджетом. Все три профиля: общий лимит контейнера 1 ГиБ, swap 0, 1 логический CPU, JDK heap128MiB/SerialGC, одинаковый датасет 4 ГиБ и uniform random поток. 1 млн прогревочных GET и 5 млн измеряемых GET (1000 пакетов по5000). Checksum совпала: -8131224688047484273. OOM не было.

Отключены native block cache и row cache, fill_cache=false; use_direct_reads=true, allow_mmap_reads=false. В конце каждого замера blockBytes=0, rowBytes=0. Индекс/Bloom/table-reader metadata могут оставаться в RAM: это не утверждение об отсутствии всех кешей системы. Direct I/O обходит Linux page cache для SST; кеши Windows/WSL2 и NVMe-контроллера не исключаются. Служебные file-cache bytes в snapshot не являются SST data cache.

Остальные настройки и представление данных — как в METHOD.md. Используется обычное RW open без прикладных writes, auto-compaction отключена, checksum verification включена, сжатие отключено. Native statistics включена. Для двух MultiGet меняется только LD_PRELOAD: с hook RocksDbIOUringEnable или без него; ReadOptions async остается true в обоих случаях, чтобы не менять дополнительный фактор. Наименование профиля с -async не доказывает использование rings; активность backend определяется hook и проверялась отдельными трассировками в предыдущей серии на том же backend.

'''
s+='| API | Время, с | GET/с | Среднее, мкс/ключ | CPU одного ядра, % |\n|---|---:|---:|---:|---:|\n'
for r in rows:s+=f"| {names[r['label']]} | {r['seconds']:.3f} | {r['getsPerSecond']:.0f} | {r['nsPerGet']/1000:.3f} | {r['cpuPctOneCore']:.2f} |\n"
s+='\nПерцентили целого пакета5000 ключей, мс (не отдельных ключей MultiGet):\n\n| API | p50 | p95 | p99 | p99.9 | max |\n|---|---:|---:|---:|---:|---:|\n'
for r in rows:s+='| '+names[r['label']]+' | '+' | '.join(f"{r[k]:.3f}" for k in ['batchP50Ms','batchP95Ms','batchP99Ms','batchP999Ms','batchMaxMs'])+' |\n'
s+='\n| API | RSS в конце, МиБ | File cache, МиБ | CPU time, с | GC, мс | Прочитано, МиБ | Read IOPS |\n|---|---:|---:|---:|---:|---:|---:|\n'
for r in rows:s+=f"| {names[r['label']]} | {r['rssEndMiB']:.1f} | {r['fileCacheEndMiB']:.1f} | {r['cpuSeconds']:.2f} | {r['gcMillis']} | {r['readMiB']:.1f} | {r['blockDeviceReadIOPS']:.0f} |\n"
d={r['label']:r for r in rows}
s+=f"\nВ этой серии MultiGet с io_uring быстрее варианта без него в {d['nocache-multi']['getsPerSecond']/d['nocache-multi-no-uring']['getsPerSecond']:.2f} раза. Сравнение с предыдущей серией кешированных данных не парное: Docker был перезапущен между сериями, возможны изменения фоновой нагрузки/нижних кешей. Полученные ~48,6 тыс./с против прежних ~45,7 тыс./с не доказывают, что отключение кеша всегда ускоряет RocksDB. Полный прогон один на конфигурацию, доверительные интервалы не оценивались.\n"
s+='''
Сырые логи, configs, counters и summary.json: results/nocache/. Запуск: собрать Dockerfile.uring в one-nio-rocks-bench:nocache, затем ./run-nocache.ps1 и ./run-nocache-no-uring.ps1. Анализ: python analyze.py --suite nocache; python report-nocache.py.

Для стенда используется seccomp=unconfined, это отключение всего seccomp-фильтра контейнера, а не готовая production-конфигурация безопасности. Для production политика io_uring и изоляции должна проверяться отдельно. Linux позволяет ограничивать создание rings через io_uring_disabled/io_uring_group: https://www.kernel.org/doc/html/v6.12/admin-guide/sysctl/kernel.html#io-uring-disabled .
'''
s += '\n\nОбласть исследования и ограничения выводов: [INTERPRETATION.md](INTERPRETATION.md). Одиночный Get не использует io_uring.\n'
(p/'NOCACHE.md').write_text(s,encoding='utf-8')
for f in ('METHOD.md','RESULTS.md'):
 t=(p/f).read_text(encoding='utf-8');marker='\n<!-- NOCACHE_APPENDIX -->\n'
 t=t.split(marker)[0]+marker+'\n'+s
 (p/f).write_text(t,encoding='utf-8')
t=(p/'README.md').read_text(encoding='utf-8')
if '[Дополнительные тесты без кешей](NOCACHE.md)' not in t:t='[Дополнительные тесты без кешей](NOCACHE.md): Get, MultiGet с io_uring и без него; Direct I/O, по5млн GET, общий RAM1ГиБ.\n\n'+t
(p/'README.md').write_text(t,encoding='utf-8')
