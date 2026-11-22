# Результаты повторной серии с равным общим бюджетом RAM

**Все четыре профиля:** контейнер 1 ГиБ RAM, swap 0, один разрешенный CPU №2; 1 млн warmup GET и 5 млн измеряемых GET (1000 пакетов × 5000). Native cache RocksDB 768 МиБ находится внутри общего лимита, а не добавляется к нему. Контрольные суммы совпали, OOM не было. Лимиты каждого контейнера проверены по сохраненному Docker inspect.

| API | Время, с | GET/с | Среднее, мкс/ключ | CPU одного ядра, % |
|---|---:|---:|---:|---:|
| one-nio | 1008.250 | 4959 | 201.650 | 14.04 |
| RocksDB Get (без io_uring) | 847.609 | 5899 | 169.522 | 20.60 |
| MultiGet + io_uring | 109.396 | 45706 | 21.879 | 35.45 |
| MultiGet без io_uring | 778.855 | 6420 | 155.771 | 13.58 |

Перцентили **пакета из 5000 ключей**, мс:

| API | p50 | p90 | p95 | p99 | p99.9 | max |
|---|---:|---:|---:|---:|---:|---:|
| one-nio | 1005.060 | 1053.295 | 1069.548 | 1094.713 | 1123.025 | 1124.073 |
| RocksDB Get (без io_uring) | 845.677 | 871.891 | 881.328 | 894.960 | 940.573 | 1014.497 |
| MultiGet + io_uring | 108.593 | 116.392 | 119.996 | 127.599 | 134.480 | 140.902 |
| MultiGet без io_uring | 779.616 | 801.112 | 807.928 | 822.608 | 827.326 | 840.434 |

| API | RSS в конце, МиБ | File cache, МиБ | Block cache, МиБ | Row cache, МиБ | CPU time, с | GC, мс | Read I/O, МиБ | Major faults |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| one-nio | 1022.8 | 911.1 | 0.0 | 0.0 | 141.53 | 13 | 24106.7 | 6171321 |
| RocksDB Get (без io_uring) | 924.4 | 11.6 | 768.0 | 0.0 | 174.64 | 12 | 18937.9 | 0 |
| MultiGet + io_uring | 921.3 | 14.8 | 736.0 | 32.0 | 38.78 | 16 | 19092.5 | 0 |
| MultiGet без io_uring | 922.8 | 45.4 | 736.0 | 32.0 | 105.80 | 16 | 19092.6 | 0 |

Выборочные перцентили **отдельного Get**, мкс (API и потребление payload):

| API | p50 | p95 | p99 | p99.9 |
|---|---:|---:|---:|---:|
| one-nio | 159.615 | 448.511 | 590.847 | 1968.127 |
| RocksDB Get (без io_uring) | 192.383 | 229.375 | 273.151 | 1676.287 |

В этом эксперименте MultiGet с io_uring показал 45 706 GET/с. Именно MultiGet с io_uring оказался быстрее one-nio (4 959 GET/с) в 9,22 раза, одиночного RocksDB Get без io_uring (5 899 GET/с) — в 7,75 раза, а MultiGet без io_uring (6 420 GET/с) — в 7,12 раза. Отдельно: одиночный RocksDB Get без io_uring опередил one-nio примерно на 19%. Это результаты конкретного стенда, одного прогона и выбранных настроек, не универсальный рейтинг библиотек.

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

Одиночный Get использует Direct I/O через pread, без io_uring. Проверка async_io=true и ограничения: [GET-IO-URING.md](GET-IO-URING.md).
