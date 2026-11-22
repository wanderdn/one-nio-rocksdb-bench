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
