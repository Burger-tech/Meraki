"""Micro-benchmark of the Windows calls the runtime's memory tracking depends on.
python tools/syscall_bench.py   -> microseconds per call (this machine; compare bare metal ~2-6 us)."""
import ctypes, ctypes.wintypes as w, time
k=ctypes.WinDLL("kernel32",use_last_error=True)
k.VirtualAlloc.restype=ctypes.c_void_p; k.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,w.DWORD,w.DWORD]
k.VirtualProtect.argtypes=[ctypes.c_void_p,ctypes.c_size_t,w.DWORD,ctypes.POINTER(w.DWORD)]
k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k.GetCurrentProcess.restype=w.HANDLE
k.GetWriteWatch.argtypes=[w.DWORD,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(w.DWORD)]
SZ=64*1024; N=20000
def bench(name,f,n=N):
    f(); t=time.perf_counter()
    for _ in range(n): f()
    print("%-34s %7.2f us/call"%(name,(time.perf_counter()-t)/n*1e6))
p=k.VirtualAlloc(None,SZ*16,0x3000,0x04)  # MEM_COMMIT|RESERVE, RW
old=w.DWORD()
bench("VirtualProtect 64KB RO",lambda:k.VirtualProtect(p,SZ,0x02,ctypes.byref(old)))
bench("VirtualProtect 64KB RW",lambda:k.VirtualProtect(p,SZ,0x04,ctypes.byref(old)))
def toggle():
    k.VirtualProtect(p,SZ,0x02,ctypes.byref(old)); k.VirtualProtect(p,SZ,0x04,ctypes.byref(old))
bench("RO+RW toggle pair",toggle,10000)
buf=(ctypes.c_ubyte*SZ)(); done=ctypes.c_size_t(); me=k.GetCurrentProcess()
bench("ReadProcessMemory 64KB (self)",lambda:k.ReadProcessMemory(me,p,buf,SZ,ctypes.byref(done)))
small=(ctypes.c_ubyte*4096)()
bench("ReadProcessMemory 4KB (self)",lambda:k.ReadProcessMemory(me,p,small,4096,ctypes.byref(done)))
bench("memcpy 64KB (ctypes.memmove)",lambda:ctypes.memmove(buf,p,SZ))
pw=k.VirtualAlloc(None,SZ*16,0x3000|0x200000,0x04)  # MEM_WRITE_WATCH
addrs=(ctypes.c_void_p*64)(); cnt=ctypes.c_size_t(); gran=w.DWORD()
def gww():
    cnt.value=64; k.GetWriteWatch(1,pw,SZ*16,addrs,ctypes.byref(cnt),ctypes.byref(gran))
bench("GetWriteWatch 1MB (reset)",gww)
def fault_cycle():  # write to a read-only page via guard: measured through exception? skip
    pass
