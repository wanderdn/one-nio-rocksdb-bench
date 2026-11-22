import json
from pathlib import Path
p=Path(__file__).resolve().parent
rows=json.loads((p/'results/equal/summary.json').read_text())
assert len(rows)==4 and len({r['checksum'] for r in rows})==1
names={'equal-nio':'one-nio','equal-get':'RocksDB Get (без io_uring)','equal-multi':'MultiGet + io_uring','equal-multi-no-uring':'MultiGet без io_uring'}
rows=sorted(rows,key=lambda r:list(names).index(r['label']))
for r in rows:
 manifest=p/f"results/equal/{r['label']}.resources.json"
 if not manifest.exists(): manifest=p/f"results/equal/{r['label']}.measurement.container.json"
 resource=json.loads(manifest.read_text(encoding='utf-8-sig'))
 c=resource[0] if isinstance(resource,list) else resource
 c=c['HostConfig']
 assert c['Memory']==1073741824 and c['MemorySwap']==1073741824 and c['CpusetCpus']=='2'
 assert r['gets']==5000000 and not r['snapshots']['measure-end']['events'].get('oom_kill',0)
s='# Результаты повторной серии с равным общим бюджетом RAM\n\n**Все четыре профиля:** контейнер 1 ГиБ RAM, swap 0, один разрешенный CPU №2; 1 млн warmup GET и 5 млн измеряемых GET (1000 пакетов × 5000). Native cache RocksDB 768 МиБ находится внутри общего лимита, а не добавляется к нему. Контрольные суммы совпали, OOM не было. Лимиты каждого контейнера проверены по сохраненному Docker inspect.\n\n'
s+='| API | Время, с | GET/с | Среднее, мкс/ключ | CPU одного ядра, % |\n|---|---:|---:|---:|---:|\n'
for r in rows:s+=f"| {names[r['label']]} | {r['seconds']:.3f} | {r['getsPerSecond']:.0f} | {r['nsPerGet']/1000:.3f} | {r['cpuPctOneCore']:.2f} |\n"
s+='\nПерцентили **пакета из 5000 ключей**, мс:\n\n| API | p50 | p90 | p95 | p99 | p99.9 | max |\n|---|---:|---:|---:|---:|---:|---:|\n'
for r in rows:s+='| '+names[r['label']]+' | '+' | '.join(f"{r[k]:.3f}" for k in ['batchP50Ms','batchP90Ms','batchP95Ms','batchP99Ms','batchP999Ms','batchMaxMs'])+' |\n'
s+='\n| API | RSS в конце, МиБ | File cache, МиБ | Block cache, МиБ | Row cache, МиБ | CPU time, с | GC, мс | Read I/O, МиБ | Major faults |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n'
for r in rows:s+=f"| {names[r['label']]} | {r['rssEndMiB']:.1f} | {r['fileCacheEndMiB']:.1f} | {r['blockCacheEndMiB']:.1f} | {r['rowCacheEndMiB']:.1f} | {r['cpuSeconds']:.2f} | {r['gcMillis']} | {r['readMiB']:.1f} | {r['intervalFaults']['pgmajfault']} |\n"
s+='\nВыборочные перцентили **отдельного Get**, мкс (API и потребление payload):\n\n| API | p50 | p95 | p99 | p99.9 |\n|---|---:|---:|---:|---:|\n'
for r in rows:
 if r['getSamples']:s+='| '+names[r['label']]+' | '+' | '.join(f"{r[k]/1000:.3f}" for k in ['getP50Ns','getP95Ns','getP99Ns','getP999Ns'])+' |\n'
d={r['label']:r for r in rows};on=d['equal-multi']['getsPerSecond']
s+=f"\nПо throughput MultiGet с io_uring быстрее one-nio в {on/d['equal-nio']['getsPerSecond']:.2f} раза; тот же MultiGet с io_uring быстрее одиночного Get без io_uring в {on/d['equal-get']['getsPerSecond']:.2f}; тот же MultiGet с io_uring быстрее MultiGet без io_uring в {on/d['equal-multi-no-uring']['getsPerSecond']:.2f}. Это результаты конкретного стенда, одного прогона и выбранных настроек, не универсальный рейтинг библиотек.\n"
s+='\nRSS и полезные кеши не обязаны совпадать: одинаков именно доступный полный RAM-бюджет, включающий JVM, native memory, kernel и file cache. SST RocksDB читает Direct I/O, поэтому нулевые major faults не означают отсутствие I/O. Счетчики относятся к виртуальному block device WSL2, не гарантированным обращениям к NAND.\n\nВсе counters, user/system CPU, cache misses, GC count, snapshots: [summary.json](results/equal/summary.json). Сырые логи и настройки: `results/equal/`. Старые данные `results/cold/` не входят в это сравнение.\n'
(p/'RESULTS.md').write_text(s,encoding='utf-8')
method='''# Методика сравнения при одинаковом общем лимите памяти

Предыдущая серия с разными лимитами признана непригодной для равноресурсного сравнения. Все четыре профиля выполнены заново; ниже используются только results/equal/.

## Стенд и данные

AMD Ryzen 9 9950X3D; Samsung 990 PRO 2 TB NVMe; Docker Desktop/WSL2, Linux 6.6.87.2. Данные в Linux named volume внутри VHDX на NVMe, не bare-metal. Фоновые пользовательские контейнеры не останавливались.

JDK Temurin 21.0.7+6, one-nio 2.5.0, RocksDB Java/JNI 11.8.1, HdrHistogram 2.2.2. JNI собран из официального тега v11.8.1 с liburing, release, PORTABLE=0. Библиотека требует пересборки под другой CPU. Точный образ и контейнерные параметры доступны в Docker inspect каждого профиля.

Одинаковые данные: 10 590 480 подписок, логический размер ключей и JSON 4 294 969 164 байта. Ключ — 8-байтовый ID. Ровно 95% подписок имеют одно устройство, 5% — два. JSON содержит синтетический 163-символьный FCM-подобный token, device_id, platform, model, версии OS/app, locale, updated_at и subscription_id. Это не действительные FCM credentials. Средний JSON 397,55 байта. Значения одинаковы у обеих библиотек, сжатие отключено. Физические форматы и резервирование отличаются: файл one-nio около 7,3 ГиБ, RocksDB около 4,3 ГиБ.

## Равные ресурсы и объем

**Каждый** контейнер на прогреве и во время измерения: memory.max 1 073 741 824 байта, memory+swap 1 073 741 824 (swap запрещен), cpuset-cpus=2. Это лимит всего процесса и его kernel/file memory, а не только кеша. JVM: Xms128m Xmx128m UseSerialGC. Native caches RocksDB вместе 768 МиБ: block 768 МиБ для Get, block 736 МиБ + row 32 МиБ для обоих MultiGet. Остальная память помещается в тот же общий 1 ГиБ. Strict capacity включена. У one-nio резидентность mmap ограничивается общим cgroup; отдельного добавочного RAM ему не выделяется.

Все API: 200 пакетов warmup (1 млн GET), затем 1000 пакетов измерения (5 млн GET). Каждый пакет — 5000 новых uniform random выборок с возвращением из всего датасета. Существующие ключи, без writes и range scan. Нет фиксированного hot set. Seed измерения 0x5eed1234; warmup SEED XOR 0x12345678abcdef. Одинаковая измерительная последовательность, разные последовательности warmup и измерения. Все четыре checksum должны совпадать.

## Подготовка, открытие и кеш

Один и тот же ранее подготовленный датасет; повторные записи не нужны. Перед каждым открытием fsync и POSIX_FADV_DONTNEED только тестовых файлов исключают наследование кеша, заряженного другому cgroup. RocksDB предварительно flush/compact. Системный drop_caches не применяется.

Только открытие/relocation может проходить с лимитом 12 ГиБ, до gate. Перед warmup runner устанавливает 1 ГиБ для любого API, сохраняет measurement.container.json и отпускает процесс. Ни повышенный стартовый лимит, ни закрытие не входят в измерение. Полезный прогрев работает уже под общим лимитом. Это проверено Docker inspect и snapshot counters; file cache/native cache, reclaim и I/O записаны в лог.

## Настройки и API

one-nio: SharedMemoryLongMap<byte[]>, capacity 21 233 664 (load около 0,5), byte[] serializer, MADV_RANDOM. Для неизменяемого набора отключены TTL и access-time writes; специализированный storeSchema primitive byte[] не обходит записи. Повторное открытие проверено selftest. Все это исходно заданная read-only конфигурация, не TTL-cache workload.

RocksDB: блок 4 KiB, restart interval 1, binary+hash data index с utilization 0,75, Bloom 10 bits/key, index/filter blocks в кеше, top-level pinning, max_open_files=-1, random advice, Direct I/O, checksum verification. Auto-compaction отключена, прикладных записей нет. Get: block-rw; оба MultiGet: row-rw-async. Native statistics включена в RocksDB, ее overhead входит во время. Новая серия проверяет эти зафиксированные настройки под равным бюджетом; новый исчерпывающий поиск оптимума кешей/сжатия/блоков не проводился.

MultiGet использует обычное open без writes: read-only open может выбрать неоптимизированный CompactedDBImpl. Runtime weak hook RocksDbIOUringEnable включается отдельной preload-библиотекой. Для варианта без io_uring убрана только эта библиотека из LD_PRELOAD, liburing оставлена для разрешения JNI symbols. ReadOptions async и остальные параметры сохранены. Проверка strace отдельно от замеров: results/uring-enabled-trace.summary содержит io_uring_enter; results/cold/no-uring-trace.summary его не содержит. Те же backend и preload-настройки используются повторной серией.

## Измерение и метрики

Один поток клиента. Одиночные API вызываются 5000 раз на пакет, MultiGet один раз. Время nanoTime включает генерацию ключей, API/JNI, выделение/копирование byte[], чтение всех байтов для 64-битной checksum, sampling/histograms и progress logging. JSON не парсится, FCM-сеть не используется. Это Java end-to-end чтение, не чистая latency NAND.

Checksum сбрасывается после warmup. Все пакеты записываются в HdrHistogram: min, mean, stddev, p50/p90/p95/p99/p99.9/max. Это latency 5000 ключей. Для отдельных Get sampling каждого 16-го дает 312500 наблюдений. Таймер не калибруется и overhead не вычитается. У MultiGet нет перцентиля отдельного ключа: пакетный p99 нельзя делить на 5000. Среднее wall/число GET — амортизированное.

Также process CPU seconds/% одного CPU, CPU user/system cgroup, GC count/time, RSS/RssAnon/RssFile, anon/file/kernel, cache occupancy, native hit/miss, pgfault/pgmajfault/refault/reclaim, virtual block bytes/IOPS, memory events и context switches. Snapshot delta относится к измерению после warmup. RSS в таблице — конечный снимок, не peak. Startup VmHWM не используется как RAM замера. Major faults mmap и native block misses — разные события, их нельзя смешивать.

Один полный прогон каждого API, порядок MultiGet on, Get, one-nio, MultiGet off. Нет доверительных интервалов; небольшие разницы требуют повторов и смены порядка. WSL2/Windows/контроллер могут кешировать ниже Linux. Вывод относится к конкретным RAM budget, данным, CPU и backend, не к любой рабочей нагрузке.

## Воспроизведение

Собрать базовый образ `docker build -t one-nio-rocks-bench:1 .`, затем `docker build -f Dockerfile.uring -t one-nio-rocks-bench:equal .`. Для нового volume подготовить один раз: `docker run --rm --memory=12g --memory-swap=12g --mount type=volume,src=one-nio-rocks-bench-data-20261121,dst=/data one-nio-rocks-bench:equal prepare /data 4294967296 4096`. Существующий датасет не перезаписывается. Далее `./run-equal.ps1`; `-Resume` пропускает только завершенные профили.

Анализ: `python analyze.py --suite equal`, затем `python report-equal.py`. Анализатор проверяет количество, checksum, OOM; генератор отчета проверяет также сохраненные лимиты CPU/RAM/swap. Все raw counters и конфигурации в results/equal/. Первичные исходники: https://github.com/odnoklassniki/one-nio и https://github.com/facebook/rocksdb/tree/v11.8.1 .

## Результаты

'''
(p/'METHOD.md').write_text(method+s,encoding='utf-8')
(p/'README.md').write_text('# one-nio vs RocksDB: равный общий RAM-бюджет\n\n'+s+'\n[Методика](METHOD.md). Запуск: `./run-equal.ps1`. Предыдущая серия с неравными лимитами исключена из публикации; её коэффициенты ускорения отозваны.\n',encoding='utf-8')
