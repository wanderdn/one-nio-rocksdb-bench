"""x86_64 Linux io_uring syscall probe, no host writes or elevated capabilities."""
import ctypes
import os
import zipfile

libc = ctypes.CDLL(None, use_errno=True)
params = ctypes.create_string_buffer(256)
fd = libc.syscall(425, 8, ctypes.byref(params))
print('io_uring_setup:', fd, 'errno:', ctypes.get_errno())
if fd >= 0:
    os.close(fd)
with zipfile.ZipFile('/project/target/one-nio-rocksdb-bench-1.0.jar') as jar:
    for name in jar.namelist():
        if name.endswith('linux64.so') and 'rocksdb' in name:
            data = jar.read(name)
            print(name, 'io_uring_setup symbol/string:', b'io_uring_setup' in data,
                  'io_uring_queue_init symbol/string:', b'io_uring_queue_init' in data)
