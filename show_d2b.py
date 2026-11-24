L=open(r"C:\Meraki\.local\shader-regression\dbg-d2b.txt",encoding="utf-8",errors="replace").read().splitlines()
out=[]; seen=0
for l in L:
    if l.startswith("RECORD"):
        seen+=1
        if seen>1: break
    out.append(l)
dbg=[l for l in out if l.startswith("DBG")]
print("first-record DBG lines:",len(dbg))
print("hard-err count:",sum(1 for l in dbg if "hard-err" in l))
dd=[l for l in dbg if "descriptor read only as data" in l]
print("descriptor-as-data lines:",len(dd))
print("--- first 6 descriptor-as-data ---")
for l in dd[:6]: print(l)
print("--- around first: full DBG index ---")
idx=[i for i,l in enumerate(dbg) if "descriptor read only as data" in l]
if idx:
    i=idx[0]
    for l in dbg[max(0,i-3):i+12]: print(l)
print("--- tail ---")
for l in out[-4:]: print(l)
