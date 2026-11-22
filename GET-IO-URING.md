# Одиночный RocksDB Get и io_uring

Одиночный Get в таблицах — **Direct I/O без io_uring**. use_direct_reads=true не означает использование io_uring: синхронный POSIX Read идет через pread.

Проверили RocksDB 11.8.1 в том же JNI/backend с включенным hook RocksDbIOUringEnable и ReadOptions.asyncIo=true. Короткая диагностическая нагрузка: 10 000 uniform random GET, nocache-rw-async, один CPU, общий лимит 1 ГиБ, тот же датасет. Она выполнялась под strace и не является новым сопоставимым performance measurement.

Трассировка: **15 836 pread64, 17 io_uring_setup, 0 io_uring_enter**. В число pread64 входит открытие и первоначальная проверка значений, не только 10 000 измеряемых GET. Создание rings не доказывает отправку через них операций. Сырые данные: [summary](results/nocache/get-async-proof.summary), [log](results/nocache/get-async-proof.log).

В исходнике PosixRandomAccessFile::Read вызывается pread. В C++ есть отдельный DBImpl::GetAsync; в сборке без USE_COROUTINES он делает fallback к Get. Эта реализация не эквивалентна стандартному синхронному Java RocksDB.get(). Поэтому флаг async_io сам по себе не создает корректного профиля «Get через io_uring».

Возможные отдельные эксперименты: MultiGet с одним ключом за вызов (так и называть; подтвердить реальное использование ring трассировкой) или C++ GetAsync с подходящим coroutine/backend и JNI-обвязкой. Это другие API/сборки, их нельзя молча подставлять вместо обычного Get.

Исходники версии: [POSIX Read](https://github.com/facebook/rocksdb/blob/v11.8.1/env/io_posix.cc), [GetAsync](https://github.com/facebook/rocksdb/blob/v11.8.1/db/db_impl/db_impl.cc).