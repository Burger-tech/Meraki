"""Out-of-process CPU sampler for victory.exe (no admin, no rebuild).

python tools/cpu_sample.py --delay 330 --dur 40 --hz 100 --out DIR [--pdb PATH]

Waits for victory.exe, sleeps --delay s, then suspends each thread briefly at
--hz, records RIP, and resolves symbols through dbghelp using the PDB.
Writes DIR\samples.csv and DIR\top.txt (self time per thread and function).
"""
import argparse, ctypes, ctypes.wintypes as W, collections, os, sys, time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
dbg = ctypes.WinDLL("dbghelp")
for f, r in (("OpenThread", W.HANDLE), ("SuspendThread", W.DWORD), ("ResumeThread", W.DWORD),
             ("CreateToolhelp32Snapshot", W.HANDLE), ("OpenProcess", W.HANDLE)):
    getattr(k32, f).restype = r
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.ResumeThread.argtypes = [W.HANDLE]
k32.CloseHandle.argtypes = [W.HANDLE]
k32.GetThreadContext.argtypes = [W.HANDLE, ctypes.c_void_p]

class TE(ctypes.Structure):
    _fields_ = [("sz", W.DWORD), ("u", W.DWORD), ("tid", W.DWORD), ("owner", W.DWORD),
                ("b", W.LONG), ("d", W.LONG), ("f", W.DWORD)]
class PE(ctypes.Structure):
    _fields_ = [("sz", W.DWORD), ("u", W.DWORD), ("pid", W.DWORD), ("h", ctypes.c_void_p),
                ("m", W.DWORD), ("t", W.DWORD), ("pp", W.DWORD), ("pc", W.LONG), ("fl", W.DWORD),
                ("exe", ctypes.c_char * 260)]
class ME(ctypes.Structure):
    _fields_ = [("sz", W.DWORD), ("mid", W.DWORD), ("pid", W.DWORD), ("gc", W.DWORD), ("pc", W.DWORD),
                ("base", ctypes.c_void_p), ("size", W.DWORD), ("h", ctypes.c_void_p),
                ("name", ctypes.c_char * 256), ("path", ctypes.c_char * 260)]

class CTX(ctypes.Structure):  # AMD64 CONTEXT, only Rip needed (offset 0xF8)
    _fields_ = [("pad0", ctypes.c_ubyte * 0x30), ("Flags", W.DWORD), ("pad1", ctypes.c_ubyte * (0xF8 - 0x34)),
                ("Rip", ctypes.c_uint64), ("pad2", ctypes.c_ubyte * (1232 - 0x100))]

def find_pid():
    s = k32.CreateToolhelp32Snapshot(2, 0)
    e = PE(); e.sz = ctypes.sizeof(PE)
    ok = k32.Process32First(s, ctypes.byref(e)); pids = []
    while ok:
        if e.exe.lower() == b"victory.exe": pids.append(e.pid)
        ok = k32.Process32Next(s, ctypes.byref(e))
    k32.CloseHandle(s)
    return pids[0] if pids else None

def tids(pid):
    s = k32.CreateToolhelp32Snapshot(4, 0)
    e = TE(); e.sz = ctypes.sizeof(TE); out = []
    ok = k32.Thread32First(s, ctypes.byref(e))
    while ok:
        if e.owner == pid: out.append(e.tid)
        ok = k32.Thread32Next(s, ctypes.byref(e))
    k32.CloseHandle(s)
    return out

def modules(pid):
    s = k32.CreateToolhelp32Snapshot(8 | 16, pid)
    e = ME(); e.sz = ctypes.sizeof(ME); out = []
    ok = k32.Module32First(s, ctypes.byref(e))
    while ok:
        out.append((e.name.decode(), e.base, e.size, e.path.decode(errors="ignore")))
        ok = k32.Module32Next(s, ctypes.byref(e))
    k32.CloseHandle(s)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0); ap.add_argument("--dur", type=float, default=30)
    ap.add_argument("--hz", type=float, default=100); ap.add_argument("--out", required=True)
    ap.add_argument("--pdb", default=None)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    pid = None
    while not pid: pid = find_pid(); time.sleep(0.5)
    print("pid", pid, flush=True); time.sleep(a.delay)
    mods = modules(pid); main_m = [m for m in mods if m[0].lower() == "victory.exe"][0]
    base, size, path = main_m[1], main_m[2], main_m[3]
    ph = k32.OpenProcess(0x1F0FFF, False, pid)
    ths = {}
    errs = []; samples = []; t_end = time.time() + a.dur; period = 1.0 / a.hz
    while time.time() < t_end:
        t0 = time.time()
        for tid in tids(pid):
            h = ths.get(tid)
            if h is None:
                h = k32.OpenThread(0x1FFFFF, False, tid); ths[tid] = h
            if not h: continue
            if k32.SuspendThread(h) == 0xFFFFFFFF: continue
            raw = (ctypes.c_ubyte * (1232 + 16))()
            addr = (ctypes.addressof(raw) + 15) & ~15
            c = CTX.from_address(addr); c.Flags = 0x100001
            if k32.GetThreadContext(h, ctypes.c_void_p(addr)):
                samples.append((tid, c.Rip))
            elif not errs:
                errs.append(ctypes.get_last_error()); print("GetThreadContext error", errs[0], flush=True)
            k32.ResumeThread(h)
        d = period - (time.time() - t0)
        if d > 0: time.sleep(d)
    print("samples", len(samples), flush=True)
    # symbolize
    dbg.SymSetOptions(0x2 | 0x4 | 0x10000000)
    pdb = a.pdb or os.path.splitext(path)[0] + ".pdb"
    dbg.SymInitializeW.argtypes = [W.HANDLE, W.LPCWSTR, W.BOOL]
    print("SymInitialize", dbg.SymInitializeW(ph, os.path.dirname(pdb), False), flush=True)
    dbg.SymLoadModuleExW.restype = ctypes.c_uint64
    dbg.SymLoadModuleExW.argtypes = [W.HANDLE, W.HANDLE, W.LPCWSTR, W.LPCWSTR, ctypes.c_uint64, W.DWORD, ctypes.c_void_p, W.DWORD]
    print("SymLoadModule", dbg.SymLoadModuleExW(ph, None, path, None, base, size, None, 0), ctypes.get_last_error(), flush=True)
    for n, b, sz, mp in mods:
        if n.lower() != "victory.exe" and mp:
            dbg.SymLoadModuleExW(ph, None, mp, None, b, sz, None, 0)
    class SYM(ctypes.Structure):
        _fields_ = [("SizeOfStruct", W.ULONG), ("TypeIndex", W.ULONG), ("Reserved", ctypes.c_uint64 * 2),
                    ("Index", W.ULONG), ("Size", W.ULONG), ("ModBase", ctypes.c_uint64), ("Flags", W.ULONG),
                    ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64), ("Register", W.ULONG),
                    ("Scope", W.ULONG), ("Tag", W.ULONG), ("NameLen", W.ULONG), ("MaxNameLen", W.ULONG),
                    ("Name", ctypes.c_char * 512)]
    def sym(rip):
        for n, b, sz, _p in mods:
            if b <= rip < b + sz:
                s = SYM(); s.SizeOfStruct = 88; s.MaxNameLen = 512; disp = ctypes.c_uint64()
                if dbg.SymFromAddr(ph, ctypes.c_uint64(rip), ctypes.byref(disp), ctypes.byref(s)) and s.Name:
                    return n + "!" + s.Name.decode(errors="ignore")
                if n.lower() != "victory.exe": return n
                s = SYM(); s.SizeOfStruct = 88; s.MaxNameLen = 512; disp = ctypes.c_uint64()
                if dbg.SymFromAddr(ph, ctypes.c_uint64(rip), ctypes.byref(disp), ctypes.byref(s)):
                    return s.Name.decode(errors="ignore")
                return "victory.exe+%x" % (rip - base)
        return "?"
    cache = {}; fn = collections.Counter(); th = collections.Counter(); thfn = collections.defaultdict(collections.Counter)
    with open(os.path.join(a.out, "samples.csv"), "w") as f:
        for tid, rip in samples:
            s = cache.get(rip) or cache.setdefault(rip, sym(rip))
            f.write("%d,%x,%s\n" % (tid, rip, s)); fn[s] += 1; th[tid] += 1; thfn[tid][s] += 1
    with open(os.path.join(a.out, "top.txt"), "w") as f:
        f.write("total %d samples\n\nthreads:\n" % len(samples))
        for t, n in th.most_common(12):
            f.write("  tid %d  %d\n" % (t, n))
            for s, m in thfn[t].most_common(12): f.write("      %5d  %s\n" % (m, s))
        f.write("\nall:\n")
        for s, n in fn.most_common(40): f.write("  %6d  %s\n" % (n, s))
    print(open(os.path.join(a.out, "top.txt")).read())
main()
