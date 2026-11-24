p=r"C:\Meraki\.local\shader-regression\dbg.txt"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()
out=[]; n=0
for l in L:
    if l.startswith("DBG"):
        n+=1
        if n>1: break
    out.append(l)
print("\n".join(out[:60]))
