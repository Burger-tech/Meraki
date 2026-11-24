L=open(r"C:\Meraki\.local\shader-regression\dbg-ffe2.txt",encoding="utf-8",errors="replace").read().splitlines()
# first record only
out=[]; seen=0
for l in L:
    if l.startswith("RECORD"):
        seen+=1
        if seen>1: break
    out.append(l)
dbg=[l for l in out if l.startswith("DBG")]
print("first-record DBG lines:",len(dbg))
print("--- first 8 ---")
for l in dbg[:8]: print(l)
print("--- last 45 ---")
for l in dbg[-45:]: print(l)
print("--- non-DBG tail ---")
for l in out[-6:]: print(l)
