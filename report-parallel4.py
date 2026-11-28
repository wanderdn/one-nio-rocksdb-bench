import json
from pathlib import Path
root=Path(__file__).resolve().parent
rows=json.loads((root/'results/parallel4/summary.json').read_text())
assert len(rows)==4
assert {r['checksum'] for r in rows}=={-8131224688047484273}
lines=['# Четыре потока и MultiGet по 32 ключа','', 'Датасет и настройки хранения прежние: 4 ГиБ логических ключей и JSON, случайные ключи из всего датасета. На каждый API — 1 млн GET прогрева и 5 млн измеряемых GET (1000 пакетов по 5000). Один полный прогон без доверительных интервалов.', '', 'Контейнер: 4 логических CPU, 1 ГиБ памяти, swap отключён. Java: heap 128 МиБ, SerialGC. RocksDB: суммарно 768 МиБ native cache; MultiGet — 736 МиБ block cache + 32 МиБ row cache. one-nio использует mmap и файловый кеш внутри того же лимита контейнера. Во время открытия one-nio временно выделяется 12 ГиБ для переноса указателей; лимит снижается до 1 ГиБ до прогрева и замера, как в исходной серии.', '', 'Четыре постоянных рабочих потока. Каждый пакет дожидается завершения всех четырёх задач. Для Get и one-nio каждый поток читает 1250 ключей. MultiGet: 156 запросов по 32 ключа и один на 8; запросы распределены между потоками циклически. Генерация ключей, диспетчеризация, ожидание и проверка значений включены во время пакета. Контрольные суммы всех API совпадают с исходной серией.', '', '## Результаты','', '| API | GET/с | Время, с | CPU, % одного ядра | CPU, % четырёх ядер | Пакет p50, мс | p95 | p99 | p99.9 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for r in rows:
 lines.append(f"| {r['label']} | {r['getsPerSecond']:.0f} | {r['seconds']:.3f} | {r['cpuPctOneCore']:.2f} | {r['cpuPctFourCores']:.2f} | {r['batchP50Ms']:.3f} | {r['batchP95Ms']:.3f} | {r['batchP99Ms']:.3f} | {r['batchP999Ms']:.3f} |")
lines+=['','## Задержка API-запроса','', 'Для Get/one-nio измеряется выборка 1 из 16 отдельных GET. Для MultiGet измеряется каждый запрос до 32 ключей, включая обработку возвращённых значений. Перцентили MultiGet относятся к запросу целиком: делить p99 на 32 для получения p99 отдельного ключа нельзя. Поля getP* в сырых METRICS для MultiGet содержат задержку запроса, сохранённую в совместимом формате; явные единицы и размер запроса указаны в REQUEST_METRICS.', '', '| API | p50, мкс | p95 | p99 | p99.9 | max |', '|---|---:|---:|---:|---:|---:|']
for r in rows:
 m=r['requestMetrics']; lines.append(f"| {r['label']} | {m['p50Us']:.3f} | {m['p95Us']:.3f} | {m['p99Us']:.3f} | {m['p999Us']:.3f} | {m['maxUs']:.3f} |")
lines+=['','## Ресурсы','', '| API | CPU time, с | RSS в конце, МиБ | File cache, МиБ | Прочитано, МиБ | Major faults | GC, мс |', '|---|---:|---:|---:|---:|---:|---:|']
for r in rows:
 lines.append(f"| {r['label']} | {r['cpuSeconds']:.2f} | {r['rssEndMiB']:.1f} | {r['fileCacheEndMiB']:.1f} | {r['readMiB']:.1f} | {r['intervalFaults']['pgmajfault']} | {r['gcMillis']} |")
lines+=['','## Воспроизведение','', 'Сначала подготовить исходный образ `one-nio-rocks-bench:equal` и датасет по REPRODUCE.md, затем:', '', '```powershell', 'docker build -f Dockerfile.parallel4 -t one-nio-rocks-bench:parallel4 .', './run-parallel4.ps1', 'python analyze.py --suite parallel4', 'python report-parallel4.py', '```', '', 'Это отдельный сценарий. С исходной серией одновременно изменены число CPU, число потоков и размер MultiGet (5000 → 32), поэтому отношение throughput между сериями не является чистой оценкой масштабирования по CPU. Стенд WSL2/NVMe и один прогон не дают универсального рейтинга библиотек. Direct I/O RocksDB обходит гостевой page cache для SST, но не кеши хоста и накопителя. Профили с io_uring используют прежнюю нативную сборку и hook; обычный Get остаётся синхронным без io_uring. Настройка seccomp=unconfined предназначена только для стенда.']
(root/'PARALLEL4.md').write_text('\n'.join(lines)+'\n')
for path in (root/'results/parallel4').glob('*.measurement.container.json'):
 c=json.loads(path.read_text(encoding='utf-8-sig'))[0]
 safe={'HostConfig':{k:c['HostConfig'][k] for k in ('Memory','MemorySwap','CpusetCpus')},'Config':{'Image':c['Config']['Image'],'Env':[e for e in c['Config']['Env'] if e.startswith(('BENCH_','LD_PRELOAD='))]}}
 assert safe['HostConfig']['Memory']==1073741824
 assert safe['HostConfig']['MemorySwap']==1073741824
 assert safe['HostConfig']['CpusetCpus']=='2-5'
 path.with_name(path.name.replace('.measurement.container.json','.resources.json')).write_text(json.dumps(safe,indent=2)+'\n')
print((root/'PARALLEL4.md').read_text())
