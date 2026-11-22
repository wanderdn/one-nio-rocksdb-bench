# Методика сравнения при одинаковом общем лимите памяти

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

# Результаты повторной серии с равным общим бюджетом RAM

**Все четыре профиля:** контейнер 1 ГиБ RAM, swap 0, один разрешенный CPU №2; 1 млн warmup GET и 5 млн измеряемых GET (1000 пакетов × 5000). Native cache RocksDB 768 МиБ находится внутри общего лимита, а не добавляется к нему. Контрольные суммы совпали, OOM не было. Лимиты каждого контейнера проверены по сохраненному Docker inspect.

| API | Время, с | GET/с | Среднее, мкс/ключ | CPU одного ядра, % |
|---|---:|---:|---:|---:|
| one-nio | 1008.250 | 4959 | 201.650 | 14.04 |
| RocksDB Get | 847.609 | 5899 | 169.522 | 20.60 |
| MultiGet + io_uring | 109.396 | 45706 | 21.879 | 35.45 |
| MultiGet без io_uring | 778.855 | 6420 | 155.771 | 13.58 |

Перцентили **пакета из 5000 ключей**, мс:

| API | p50 | p90 | p95 | p99 | p99.9 | max |
|---|---:|---:|---:|---:|---:|---:|
| one-nio | 1005.060 | 1053.295 | 1069.548 | 1094.713 | 1123.025 | 1124.073 |
| RocksDB Get | 845.677 | 871.891 | 881.328 | 894.960 | 940.573 | 1014.497 |
| MultiGet + io_uring | 108.593 | 116.392 | 119.996 | 127.599 | 134.480 | 140.902 |
| MultiGet без io_uring | 779.616 | 801.112 | 807.928 | 822.608 | 827.326 | 840.434 |

| API | RSS в конце, МиБ | File cache, МиБ | Block cache, МиБ | Row cache, МиБ | CPU time, с | GC, мс | Read I/O, МиБ | Major faults |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| one-nio | 1022.8 | 911.1 | 0.0 | 0.0 | 141.53 | 13 | 24106.7 | 6171321 |
| RocksDB Get | 924.4 | 11.6 | 768.0 | 0.0 | 174.64 | 12 | 18937.9 | 0 |
| MultiGet + io_uring | 921.3 | 14.8 | 736.0 | 32.0 | 38.78 | 16 | 19092.5 | 0 |
| MultiGet без io_uring | 922.8 | 45.4 | 736.0 | 32.0 | 105.80 | 16 | 19092.6 | 0 |

Выборочные перцентили **отдельного Get**, мкс (API и потребление payload):

| API | p50 | p95 | p99 | p99.9 |
|---|---:|---:|---:|---:|
| one-nio | 159.615 | 448.511 | 590.847 | 1968.127 |
| RocksDB Get | 192.383 | 229.375 | 273.151 | 1676.287 |

По throughput MultiGet с io_uring быстрее one-nio в 9.22 раза, Get — в 7.75, MultiGet без io_uring — в 7.12. Это результаты конкретного стенда, одного прогона и выбранных настроек, не универсальный рейтинг библиотек.

RSS и полезные кеши не обязаны совпадать: одинаков именно доступный полный RAM-бюджет, включающий JVM, native memory, kernel и file cache. SST RocksDB читает Direct I/O, поэтому нулевые major faults не означают отсутствие I/O. Счетчики относятся к виртуальному block device WSL2, не гарантированным обращениям к NAND.

Все counters, user/system CPU, cache misses, GC count, snapshots: [summary.json](results/equal/summary.json). Сырые логи и настройки: `results/equal/`. Старые данные `results/cold/` не входят в это сравнение.

<!-- NOCACHE_APPENDIX -->

# RocksDB без кешей данных: Direct I/O

Дополнение к серии с равным RAM-бюджетом. Все три профиля: общий лимит контейнера 1 ГиБ, swap 0, CPU №2, JDK heap128MiB/SerialGC, одинаковый датасет 4 ГиБ и uniform random поток. 1 млн прогревочных GET и 5 млн измеряемых GET (1000 пакетов по5000). Checksum совпала: -8131224688047484273. OOM не было.

Отключены native block cache и row cache, fill_cache=false; use_direct_reads=true, allow_mmap_reads=false. В конце каждого замера blockBytes=0, rowBytes=0. Индекс/Bloom/table-reader metadata могут оставаться в RAM: это не утверждение об отсутствии всех кешей системы. Direct I/O обходит Linux page cache для SST; кеши Windows/WSL2 и NVMe-контроллера не исключаются. Служебные file-cache bytes в snapshot не являются SST data cache.

Остальные настройки и представление данных — как в METHOD.md. Используется обычное RW open без прикладных writes, auto-compaction отключена, checksum verification включена, сжатие отключено. Native statistics включена. Для двух MultiGet меняется только LD_PRELOAD: с hook RocksDbIOUringEnable или без него; ReadOptions async остается true в обоих случаях, чтобы не менять дополнительный фактор. Наименование профиля с -async не доказывает использование rings; активность backend определяется hook и проверялась отдельными трассировками в предыдущей серии на том же backend.

| API | Время, с | GET/с | Среднее, мкс/ключ | CPU одного ядра, % |
|---|---:|---:|---:|---:|
| Get, Direct I/O | 1039.916 | 4808 | 207.983 | 16.95 |
| MultiGet, Direct I/O, без io_uring | 955.850 | 5231 | 191.170 | 10.63 |
| MultiGet, Direct I/O + io_uring | 102.948 | 48568 | 20.590 | 24.05 |

Перцентили целого пакета5000 ключей, мс (не отдельных ключей MultiGet):

| API | p50 | p95 | p99 | p99.9 | max |
|---|---:|---:|---:|---:|---:|
| Get, Direct I/O | 1036.517 | 1081.082 | 1092.616 | 1095.762 | 1099.956 |
| MultiGet, Direct I/O, без io_uring | 959.447 | 990.380 | 1000.342 | 1005.584 | 1005.584 |
| MultiGet, Direct I/O + io_uring | 102.564 | 108.986 | 111.739 | 119.013 | 133.235 |

| API | RSS в конце, МиБ | File cache, МиБ | CPU time, с | GC, мс | Прочитано, МиБ | Read IOPS |
|---|---:|---:|---:|---:|---:|---:|
| Get, Direct I/O | 201.5 | 11.7 | 176.21 | 12 | 22650.7 | 4808 |
| MultiGet, Direct I/O, без io_uring | 171.8 | 42.4 | 101.58 | 15 | 22588.1 | 5196 |
| MultiGet, Direct I/O + io_uring | 169.3 | 22.0 | 24.76 | 14 | 22588.1 | 48240 |

В этой серии MultiGet с io_uring быстрее варианта без него в 9.28 раза. Сравнение с предыдущей серией кешированных данных не парное: Docker был перезапущен между сериями, возможны изменения фоновой нагрузки/нижних кешей. Полученные ~48,6 тыс./с против прежних ~45,7 тыс./с не доказывают, что отключение кеша всегда ускоряет RocksDB. Полный прогон один на конфигурацию, доверительные интервалы не оценивались.

Сырые логи, configs, counters и summary.json: results/nocache/. Запуск: собрать Dockerfile.uring в one-nio-rocks-bench:nocache, затем ./run-nocache.ps1 и ./run-nocache-no-uring.ps1. Анализ: python analyze.py --suite nocache; python report-nocache.py.

Для стенда используется seccomp=unconfined, это отключение всего seccomp-фильтра контейнера, а не готовая production-конфигурация безопасности. Для production политика io_uring и изоляции должна проверяться отдельно. Linux позволяет ограничивать создание rings через io_uring_disabled/io_uring_group: https://www.kernel.org/doc/html/v6.12/admin-guide/sysctl/kernel.html#io-uring-disabled .
