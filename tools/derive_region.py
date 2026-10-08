"""Derive the addresses ChainKit needs in another build of Burnout Revenge (USA SLUS_212.42) from the PAL build.

Both executables are the same compiler output with small shifts. This script aligns the two code segments by masked
instruction windows (jump targets and address immediates masked out, like MusicKit's signatures), then
- maps every PAL code address ChainKit uses (hook sites, return points, called functions) to the aligned USA word;
- maps every PAL data address through the lui + addiu/load/store pairs and jal targets of aligned code (each USA
  data address must be confirmed by at least one aligned reference; addresses inside a table use the delta of the
  table's own base reference, checked against the neighbouring references).
Nothing is guessed: an address that cannot be confirmed is an error.

    python tools/derive_region.py PAL_ELF USA_ELF          -> prints the USA address table (Python dict)
Both files are read from your own discs (e.g. extracted with `chainkit` or any ISO tool); none is in this repository.
"""
import struct
import sys
from collections import Counter, defaultdict

LOADSTORE = {0x09, 0x0D, 0x0C, 0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x31, 0x39, 0x37, 0x3F, 0x1E, 0x1F,
             0x0A, 0x0B}
MEMOPS = {0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x31, 0x39, 0x37, 0x3F, 0x1E, 0x1F}


def load(path):
    d = open(path, "rb").read()
    phoff = struct.unpack_from("<I", d, 0x1C)[0]
    ph = [struct.unpack_from("<8I", d, phoff + 32 * i) for i in range(struct.unpack_from("<H", d, 0x2C)[0])]
    s0 = ph[0]
    n = s0[4] // 4
    words = list(struct.unpack_from("<%dI" % n, d, s0[1]))
    return d, ph, s0[2], words


def mask(w):
    op = w >> 26
    if op in (2, 3):
        return op << 26
    if op == 0x0F:
        return w & 0xFFFF0000
    if op in LOADSTORE:
        return w & 0xFFFF0000
    return w


def align(pw, uw, k=10):
    pm = [mask(w) for w in pw]
    um = [mask(w) for w in uw]

    def grams(m):
        c = defaultdict(list)
        for i in range(0, len(m) - k):
            c[tuple(m[i:i + k])].append(i)
        return c
    gp, gu = grams(pm), grams(um)
    anchors = []
    for g, ip in gp.items():
        if len(ip) == 1:
            iu = gu.get(g)
            if iu and len(iu) == 1 and any(x for x in g):
                anchors.append((ip[0], iu[0]))
    anchors.sort()
    # keep anchors whose delta agrees with their neighbours (drop stray matches)
    good = []
    for n, (i, j) in enumerate(anchors):
        d = j - i
        near = [b - a for a, b in anchors[max(0, n - 3):n + 4]]
        if sum(1 for x in near if x == d) >= 3:
            good.append((i, j))
    mp = {}
    for (i, j), nxt in zip(good, good[1:] + [(len(pw), None)]):
        d = j - i
        for x in range(i, nxt[0]):
            y = x + d
            if 0 <= y < len(uw) and pm[x] == um[y]:
                mp[x] = y
    return mp


def gp_value(base, words):
    """$gp as set by crt0 (a0 of `daddu gp, a0, zero`, found by its pattern near the entry point)."""
    for i in range(0, 0x200):
        if words[i] == 0x0080E02D:
            pc = base + 4 * i
            return evaluate(base, words, pc - 0x28, pc, "a0")
    raise SystemExit("crt0 $gp setup not found")


def refs(base, words, idx_list=None, gp=None):
    """{pc index: (address, kind)} for lui/addiu|mem pairs, $gp-relative accesses and jal targets."""
    out = {}
    hi = {}
    rng = range(len(words)) if idx_list is None else idx_list
    for i in rng:
        w = words[i]
        op = w >> 26
        if op == 3:
            out[i] = ((((base + 4 * i) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)), "jal")
        if op == 0x0F:
            hi[(w >> 16) & 31] = (i, (w & 0xFFFF) << 16)
            continue
        if gp is not None and (op == 0x09 or op in MEMOPS) and ((w >> 21) & 31) == 28:
            imm = w & 0xFFFF
            out[i] = ((gp + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF, "data")
            continue
        if op in (0x09, 0x0D) or op in MEMOPS:
            rs = (w >> 21) & 31
            if rs in hi and i - hi[rs][0] < 12:
                imm = w & 0xFFFF
                if op == 0x0D:
                    a = hi[rs][1] | imm
                else:
                    a = (hi[rs][1] + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                out[i] = (a, "data")
                if op in (0x09, 0x0D) and ((w >> 16) & 31) == rs:
                    pass
        # a branch / jump ends the lui tracking window for safety
        if op in (1, 2, 4, 5, 6, 7) or (op == 0 and (w & 0x3F) in (8, 9)):
            hi = {k: v for k, v in hi.items() if i - v[0] < 2}
    return out


def evaluate(base, words, start, end, reg):
    """Value of register `reg` after running the lui/ori/addiu/addu instructions in [start, end)."""
    R = {0: 0}
    names = {"v0": 2, "v1": 3, "a0": 4, "a1": 5}
    for pc in range(start, end, 4):
        w = words[(pc - base) // 4]
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:
            R[rt] = imm << 16
        elif op == 0x0D:
            R[rt] = R.get(rs, 0) | imm
        elif op == 0x09:
            R[rt] = (R.get(rs, 0) + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
        elif op == 0 and (w & 0x3F) in (0x21, 0x2D):
            R[(w >> 11) & 31] = (R.get(rs, 0) + R.get(rt, 0)) & 0xFFFFFFFF
    return R[names[reg]]


def derive(pal_path, usa_path, code_addrs, data_addrs, computed=None):
    _, _, pb, pw = load(pal_path)
    _, _, ub, uw = load(usa_path)
    mp = align(pw, uw)
    code = {}
    for a in code_addrs:
        i = (a - pb) // 4
        if i not in mp:
            raise SystemExit("code address %#x not aligned" % a)
        code[a] = ub + 4 * mp[i]
    pr = refs(pb, pw, gp=gp_value(pb, pw))
    ur = refs(ub, uw, gp=gp_value(ub, uw))
    pairs = Counter()
    for i, (a, kind) in pr.items():
        j = mp.get(i)
        if j is None or j not in ur:
            continue
        b, kind2 = ur[j]
        if kind == kind2:
            pairs[(a, b)] += 1
    by_pal = defaultdict(Counter)
    for (a, b), n in pairs.items():
        by_pal[a][b] += n
    data = {}
    for a in data_addrs:
        if a in by_pal:
            b, n = by_pal[a].most_common(1)[0]
            if len(by_pal[a]) > 1 and by_pal[a].most_common(2)[1][1] * 4 > n:
                raise SystemExit("ambiguous mapping for %#x: %s" % (a, dict(by_pal[a])))
            data[a] = (b, n, "exact")
            continue
        # not referenced directly (reached through a base register + offset): the delta of the surrounding
        # references; they must agree (>= 85 % of them, at least 3)
        for win in (0x400, 0x1000, 0x4000):
            votes = Counter()
            for x, c in by_pal.items():
                if abs(x - a) <= win:
                    for b, n in c.items():
                        votes[b - x] += n
            total = sum(votes.values())
            if total >= 3:
                d, n = votes.most_common(1)[0]
                if n >= 0.85 * total:
                    data[a] = (a + d, n, "neighbours within %#x (%d/%d agree)" % (win, n, total))
                    break
        else:
            raise SystemExit("data address %#x: no agreeing references around it" % a)
    for a, (start, end, reg) in (computed or {}).items():
        if evaluate(pb, pw, start, end, reg) != a:
            raise SystemExit("computed address %#x: PAL code at %#x does not give it" % (a, start))
        i0, i1 = (start - pb) // 4, (end - pb) // 4
        if any(i not in mp for i in range(i0, i1)) or mp[i1 - 1] - mp[i0] != i1 - 1 - i0:
            raise SystemExit("computed address %#x: code at %#x not aligned" % (a, start))
        us = ub + 4 * mp[i0]
        data[a] = (evaluate(ub, uw, us, us + (end - start), reg), 1, "computed at %#x" % us)
    return code, data, mp, (pb, pw, ub, uw)


def usa_map(pal_path, usa_path):
    """{PAL address: USA address} for everything ChainKit uses, plus notes per data address."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from chainkit import regions
    code, data, mp, _ = derive(pal_path, usa_path, regions.PAL_CODE_ADDRS, regions.PAL_DATA_ADDRS,
                               regions.PAL_COMPUTED)
    out = dict(code)
    out.update({a: b for a, (b, n, how) in data.items()})
    return out, data


if __name__ == "__main__":
    m, data = usa_map(sys.argv[1], sys.argv[2])
    print("USA_MAP = {")
    items = sorted(m.items())
    for k in range(0, len(items), 4):
        print("    " + " ".join("0x%06X: 0x%06X," % kv for kv in items[k:k + 4]))
    print("}")
    for a, (b, n, how) in sorted(data.items()):
        print("# data %#08x -> %#08x  (%+#x) %s" % (a, b, b - a, how))
