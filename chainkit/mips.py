"""Tiny R5900 (PS2 EE) assembler DSL + interpreter for the instruction subset ChainKit uses.

Assembler: `a = Asm(base); a.addiu("t0", "t0", 4); a.label("x"); a.beq("t0", "zero", "x"); a.nop(); data = a.assemble()`.
Branch/jump targets are label names or absolute addresses; every branch/jump is followed by an explicit delay slot.
The interpreter (`Cpu`) runs the same subset on a sparse memory so the cave code can be unit-tested; calls to
addresses registered in `Cpu.stubs` run Python functions instead (then return to $ra).
"""
import struct

REGS = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
        "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra"]
RI = {n: i for i, n in enumerate(REGS)}
RI["s8"] = 30


def r(n):
    return RI[n] if isinstance(n, str) else n


def f(n):
    if isinstance(n, int):
        return n
    assert n.startswith("f")
    return int(n[1:])


def f2u(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def u2f(u):
    return struct.unpack("<f", struct.pack("<I", u & 0xFFFFFFFF))[0]


def hi16(a):
    return ((a + 0x8000) >> 16) & 0xFFFF


def lo16(a):
    return a & 0xFFFF


R_FUNCT = {"sll": 0x00, "srl": 0x02, "sra": 0x03, "sllv": 0x04, "jr": 0x08, "jalr": 0x09, "addu": 0x21, "subu": 0x23,
           "and_": 0x24, "or_": 0x25, "xor": 0x26, "nor": 0x27, "slt": 0x2A, "sltu": 0x2B, "daddu": 0x2D}
I_OP = {"beq": 4, "bne": 5, "blez": 6, "bgtz": 7, "addiu": 9, "slti": 10, "sltiu": 11, "andi": 12, "ori": 13,
        "xori": 14, "lui": 15, "lq": 0x1E, "sq": 0x1F, "lb": 0x20, "lh": 0x21, "lw": 0x23, "lbu": 0x24, "lhu": 0x25,
        "sb": 0x28, "sh": 0x29, "sw": 0x2B, "lwc1": 0x31, "ld": 0x37, "swc1": 0x39, "sd": 0x3F}
FP_FUNCT = {"add_s": 0, "sub_s": 1, "mul_s": 2, "div_s": 3, "abs_s": 5, "mov_s": 6, "neg_s": 7, "cvt_w_s": 0x24}
FP_CMP = {"c_eq_s": 0x32, "c_lt_s": 0x34, "c_le_s": 0x36}


class Asm:
    def __init__(self, base):
        self.base = base
        self.items = []          # (kind, payload)
        self.labels = {}

    @property
    def pc(self):
        return self.base + 4 * len(self.items)

    def label(self, name):
        if name in self.labels:
            raise ValueError("duplicate label " + name)
        self.labels[name] = self.pc

    def word(self, w):
        self.items.append(("w", w & 0xFFFFFFFF))

    # ---- encoders
    def _r(self, funct, rd=0, rs=0, rt=0, sa=0):
        self.word((r(rs) << 21) | (r(rt) << 16) | (r(rd) << 11) | ((sa & 31) << 6) | funct)

    def _i(self, op, rt, rs, imm):
        if not -0x8000 <= imm <= 0xFFFF:
            raise ValueError("immediate out of range: %#x" % imm)
        self.word((op << 26) | (r(rs) << 21) | (r(rt) << 16) | (imm & 0xFFFF))

    def nop(self):
        self.word(0)

    def __getattr__(self, name):
        if name in R_FUNCT:
            fn = R_FUNCT[name]
            if name in ("sll", "srl", "sra"):
                return lambda rd, rt, sa: self._r(fn, rd=rd, rt=rt, sa=sa)
            if name == "sllv":
                return lambda rd, rt, rs: self._r(fn, rd=rd, rs=rs, rt=rt)
            if name == "jr":
                return lambda rs: self._r(fn, rs=rs)
            if name == "jalr":
                return lambda rs, rd="ra": self._r(fn, rd=rd, rs=rs)
            return lambda rd, rs, rt: self._r(fn, rd=rd, rs=rs, rt=rt)
        if name in I_OP:
            op = I_OP[name]
            if name in ("beq", "bne"):
                return lambda rs, rt, target: self.items.append(("b", (op, r(rs), r(rt), target)))
            if name in ("blez", "bgtz"):
                return lambda rs, target: self.items.append(("b", (op, r(rs), 0, target)))
            if name == "lui":
                return lambda rt, imm: self._i(op, rt, 0, imm)
            if name in ("addiu", "slti", "sltiu", "andi", "ori", "xori"):
                return lambda rt, rs, imm: self._i(op, rt, rs, imm)
            if name in ("lwc1", "swc1"):
                return lambda ft, off, base: self._i(op, f(ft), base, off)
            return lambda rt, off, base: self._i(op, rt, base, off)
        if name in FP_FUNCT:
            fn = FP_FUNCT[name]
            if name in ("abs_s", "mov_s", "neg_s", "cvt_w_s"):
                return lambda fd, fs: self.word(0x46000000 | (f(fs) << 11) | (f(fd) << 6) | fn)
            return lambda fd, fs, ft: self.word(0x46000000 | (f(ft) << 16) | (f(fs) << 11) | (f(fd) << 6) | fn)
        if name in FP_CMP:
            fn = FP_CMP[name]
            return lambda fs, ft: self.word(0x46000000 | (f(ft) << 16) | (f(fs) << 11) | fn)
        raise AttributeError(name)

    def bltz(self, rs, target):
        self.items.append(("b", (1, r(rs), 0, target)))

    def bgez(self, rs, target):
        self.items.append(("b", (1, r(rs), 1, target)))

    def beqz(self, rs, target):
        self.beq(rs, "zero", target)

    def bnez(self, rs, target):
        self.bne(rs, "zero", target)

    def b(self, target):
        self.beq("zero", "zero", target)

    def bc1t(self, target):
        self.items.append(("b", ("bc1", 1, 0, target)))

    def bc1f(self, target):
        self.items.append(("b", ("bc1", 0, 0, target)))

    def j(self, target):
        self.items.append(("j", (2, target)))

    def jal(self, target):
        self.items.append(("j", (3, target)))

    def move(self, rd, rs):
        self.daddu(rd, rs, "zero")

    def mtc1(self, rt, fs):
        self.word(0x44800000 | (r(rt) << 16) | (f(fs) << 11))

    def mfc1(self, rt, fs):
        self.word(0x44000000 | (r(rt) << 16) | (f(fs) << 11))

    def cvt_s_w(self, fd, fs):
        self.word(0x46800020 | (f(fs) << 11) | (f(fd) << 6))

    def por(self, rd, rs, rt):
        self.word(0x70000000 | (r(rs) << 21) | (r(rt) << 16) | (r(rd) << 11) | (0x12 << 6) | 0x29)

    # ---- macros
    def li(self, rt, v):
        v &= 0xFFFFFFFF
        if v < 0x8000 or v >= 0xFFFF8000:
            self.addiu(rt, "zero", v - (1 << 32) if v >= 0x80000000 else v)
        elif v & 0xFFFF == 0:
            self.lui(rt, v >> 16)
        else:
            self.lui(rt, v >> 16)
            self.ori(rt, rt, v & 0xFFFF)

    def la(self, rt, addr):
        self.lui(rt, hi16(addr))
        self.addiu(rt, rt, _s16(lo16(addr)))

    def lif(self, ft, x, tmp="at"):
        self.li(tmp, f2u(x))
        self.mtc1(tmp, ft)
        self.nop()

    def mem(self, op, rt, addr, tmp):
        """op rt, %lo(addr)(tmp) after lui tmp,%hi(addr)."""
        self.lui(tmp, hi16(addr))
        getattr(self, op)(rt, _s16(lo16(addr)), tmp)

    def assemble(self):
        out = bytearray()
        for i, (k, p) in enumerate(self.items):
            pc = self.base + 4 * i
            if k == "w":
                w = p
            elif k == "b":
                op, rs, rt, t = p
                ta = self.labels[t] if isinstance(t, str) else t
                off = (ta - (pc + 4)) >> 2
                if not -0x8000 <= off < 0x8000:
                    raise ValueError("branch out of range")
                if op == "bc1":
                    w = 0x45000000 | (rs << 16) | (off & 0xFFFF)
                else:
                    w = (op << 26) | (rs << 21) | (rt << 16) | (off & 0xFFFF)
            else:
                op, t = p
                ta = self.labels[t] if isinstance(t, str) else t
                if (ta & 0xF0000000) != (pc & 0xF0000000):
                    raise ValueError("jump out of region")
                w = (op << 26) | ((ta >> 2) & 0x3FFFFFF)
            out += struct.pack("<I", w)
        return bytes(out)


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


# ----------------------------------------------------------------------------------------------- interpreter
class Mem:
    def __init__(self):
        self.pages = {}

    def _p(self, a):
        pg = self.pages.get(a >> 12)
        if pg is None:
            pg = self.pages[a >> 12] = bytearray(4096)
        return pg, a & 0xFFF

    def read(self, a, n):
        out = bytearray()
        for k in range(n):
            pg, o = self._p(a + k)
            out.append(pg[o])
        return bytes(out)

    def write(self, a, data):
        for k, b in enumerate(data):
            pg, o = self._p(a + k)
            pg[o] = b

    def u32(self, a):
        return struct.unpack("<I", self.read(a, 4))[0]

    def w32(self, a, v):
        self.write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def f32(self, a):
        return u2f(self.u32(a))

    def wf32(self, a, x):
        self.w32(a, f2u(x))


M64 = (1 << 64) - 1


def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def f32r(x):
    return u2f(f2u(x)) if x == x else x


class Cpu:
    def __init__(self, mem=None):
        self.m = mem or Mem()
        self.g = [0] * 32          # 128-bit values (python ints)
        self.fr = [0] * 32         # float bits
        self.cc = False
        self.stubs = {}
        self.trace = []
        self.steps = 0

    def gr(self, i):
        return self.g[i] & M64

    def sr(self, i, v):
        if i:
            self.g[i] = v & M64

    def s32(self, i, v):
        self.sr(i, sx(v, 32) & M64)

    def ff(self, i):
        return u2f(self.fr[i])

    def sf(self, i, x):
        self.fr[i] = f2u(f32r(x))

    def call(self, addr, ret=0xDEAD0000, max_steps=200000):
        self.g[31] = ret
        self.steps = 0
        pc = addr
        while pc != ret:
            pc = self.step(pc, ret)
            self.steps += 1
            if self.steps > max_steps:
                raise RuntimeError("runaway")
        return self

    def step(self, pc, ret):
        if pc in self.stubs:
            self.trace.append(("call", pc))
            self.stubs[pc](self)
            return self.gr(31) & 0xFFFFFFFF
        w = self.m.u32(pc)
        nxt, delay_target = self.exec1(pc, w)
        if delay_target is None:
            return nxt
        # execute delay slot
        w2 = self.m.u32(pc + 4)
        n2, d2 = self.exec1(pc + 4, w2)
        if d2 is not None:
            raise RuntimeError("branch in delay slot at %#x" % (pc + 4))
        return delay_target

    def exec1(self, pc, w):
        """Return (next_pc, None) or (None, branch_target) for control transfers (delay slot follows)."""
        op = w >> 26
        rs, rt, rd, sa, fn = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31, w & 63
        imm = sx(w & 0xFFFF, 16)
        G = self.gr
        nxt = pc + 4
        if w == 0:
            return nxt, None
        if op == 0:
            if fn == 0x00: self.s32(rd, G(rt) << sa)
            elif fn == 0x02: self.s32(rd, (G(rt) & 0xFFFFFFFF) >> sa)
            elif fn == 0x03: self.s32(rd, sx(G(rt), 32) >> sa)
            elif fn == 0x04: self.s32(rd, G(rt) << (G(rs) & 31))
            elif fn == 0x08: return None, G(rs) & 0xFFFFFFFF
            elif fn == 0x09:
                t = G(rs) & 0xFFFFFFFF
                self.sr(rd, pc + 8)
                return None, t
            elif fn == 0x21: self.s32(rd, G(rs) + G(rt))
            elif fn == 0x23: self.s32(rd, G(rs) - G(rt))
            elif fn == 0x24: self.sr(rd, G(rs) & G(rt))
            elif fn == 0x25: self.sr(rd, G(rs) | G(rt))
            elif fn == 0x26: self.sr(rd, G(rs) ^ G(rt))
            elif fn == 0x27: self.sr(rd, ~(G(rs) | G(rt)))
            elif fn == 0x2A: self.sr(rd, int(sx(G(rs), 64) < sx(G(rt), 64)))
            elif fn == 0x2B: self.sr(rd, int(G(rs) < G(rt)))
            elif fn == 0x2D: self.sr(rd, G(rs) + G(rt))
            else: raise RuntimeError("unsupported special %#x at %#x" % (w, pc))
            return nxt, None
        if op == 1:
            v = sx(G(rs), 64)
            if (rt == 0 and v < 0) or (rt == 1 and v >= 0):
                return None, pc + 4 + (imm << 2)
            return None, pc + 8
        if op in (2, 3):
            t = (pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            if op == 3:
                self.sr(31, pc + 8)
            return None, t
        if op in (4, 5, 6, 7):
            a, b = sx(G(rs), 64), sx(G(rt), 64)
            take = {4: a == b, 5: a != b, 6: a <= 0, 7: a > 0}[op]
            return None, (pc + 4 + (imm << 2)) if take else pc + 8
        if op == 9: self.s32(rt, G(rs) + imm)
        elif op == 10: self.sr(rt, int(sx(G(rs), 64) < imm))
        elif op == 11: self.sr(rt, int(G(rs) < (imm & M64)))
        elif op == 12: self.sr(rt, G(rs) & (w & 0xFFFF))
        elif op == 13: self.sr(rt, G(rs) | (w & 0xFFFF))
        elif op == 14: self.sr(rt, G(rs) ^ (w & 0xFFFF))
        elif op == 15: self.s32(rt, (w & 0xFFFF) << 16)
        elif op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x37, 0x31, 0x1E):
            a = (G(rs) + imm) & 0xFFFFFFFF
            if op == 0x20: self.sr(rt, sx(self.m.read(a, 1)[0], 8) & M64)
            elif op == 0x24: self.sr(rt, self.m.read(a, 1)[0])
            elif op == 0x21: self.sr(rt, sx(struct.unpack("<H", self.m.read(a, 2))[0], 16) & M64)
            elif op == 0x25: self.sr(rt, struct.unpack("<H", self.m.read(a, 2))[0])
            elif op == 0x23: self.s32(rt, self.m.u32(a))
            elif op == 0x37: self.sr(rt, struct.unpack("<Q", self.m.read(a, 8))[0])
            elif op == 0x31: self.fr[rt] = self.m.u32(a)
            else:
                assert a % 16 == 0, "unaligned lq"
                if rt:
                    self.g[rt] = int.from_bytes(self.m.read(a, 16), "little")
        elif op in (0x28, 0x29, 0x2B, 0x3F, 0x39, 0x1F):
            a = (G(rs) + imm) & 0xFFFFFFFF
            v = self.g[rt]
            if op == 0x28: self.m.write(a, bytes([v & 0xFF]))
            elif op == 0x29: self.m.write(a, struct.pack("<H", v & 0xFFFF))
            elif op == 0x2B: self.m.w32(a, v)
            elif op == 0x3F: self.m.write(a, struct.pack("<Q", v & M64))
            elif op == 0x39: self.m.w32(a, self.fr[rt])
            else:
                assert a % 16 == 0, "unaligned sq"
                self.m.write(a, (v & ((1 << 128) - 1)).to_bytes(16, "little"))
        elif op == 0x11:
            fmt = rs
            fs, ft, fd = rd, rt, sa
            if fmt == 0x00: self.s32(rt, self.fr[fs])                       # mfc1
            elif fmt == 0x04: self.fr[fs] = G(rt) & 0xFFFFFFFF               # mtc1
            elif fmt == 0x08:                                               # bc1f/bc1t
                take = self.cc if rt & 1 else not self.cc
                return None, (pc + 4 + (imm << 2)) if take else pc + 8
            elif fmt == 0x10:
                a, b = self.ff(fs), self.ff(ft)
                if fn == 0: self.sf(fd, a + b)
                elif fn == 1: self.sf(fd, a - b)
                elif fn == 2: self.sf(fd, a * b)
                elif fn == 3: self.sf(fd, a / b)
                elif fn == 5: self.sf(fd, abs(a))
                elif fn == 6: self.fr[fd] = self.fr[fs]
                elif fn == 7: self.sf(fd, -a)
                elif fn == 0x24: self.fr[fd] = int(a) & 0xFFFFFFFF          # cvt.w.s (truncate on EE)
                elif fn == 0x32: self.cc = a == b
                elif fn == 0x34: self.cc = a < b
                elif fn == 0x36: self.cc = a <= b
                else: raise RuntimeError("unsupported fp %#x" % w)
            elif fmt == 0x14 and fn == 0x20:
                self.sf(fd, float(sx(self.fr[fs], 32)))
            else:
                raise RuntimeError("unsupported cop1 %#x at %#x" % (w, pc))
        elif op == 0x1C and fn == 0x29 and sa == 0x12:                       # por
            if rd:
                self.g[rd] = (self.g[rs] | self.g[rt]) & ((1 << 128) - 1)
        else:
            raise RuntimeError("unsupported opcode %#x at %#x" % (w, pc))
        return nxt, None
