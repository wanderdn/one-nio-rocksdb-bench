// RocksDB's POSIX backend checks this public weak hook before using liburing.
extern "C" bool RocksDbIOUringEnable() { return true; }
