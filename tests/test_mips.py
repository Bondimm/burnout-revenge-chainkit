"""MIPS encoder round trip against capstone (optional: pip install capstone) and the interpreter."""
import os
import struct
import sys

import pytest

capstone = pytest.importorskip("capstone")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chainkit.mips import Asm, Cpu, f2u

MD = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 + capstone.CS_MODE_LITTLE_ENDIAN)


def dis(data, base):
    out = []
    for k in range(0, len(data), 4):
        ins = list(MD.disasm(data[k:k + 4], base + k))
        out.append((ins[0].mnemonic + " " + ins[0].op_str).strip() if ins else "???")
    return out


def test_encode_roundtrip():
    a = Asm(0x4A5000)
    a.label("top")
    a.addiu("t0", "a0", -4); a.lw("v0", 0x94, "s0"); a.sw("t1", -8, "sp"); a.lbu("t2", 0x9A, "s0")
    a.sb("zero", 0, "t3"); a.lui("t4", 0x4A); a.ori("t4", "t4", 0x1234); a.andi("t5", "t5", 7)
    a.sll("t6", "t6", 5); a.srl("t6", "t6", 2); a.sra("t6", "t6", 1); a.addu("t7", "t6", "t5"); a.subu("t7", "t6", "t5")
    a.slt("v1", "t0", "t1"); a.sltu("v1", "t0", "t1"); a.slti("v1", "t0", 3); a.sltiu("v1", "t0", 3)
    a.move("a0", "s0"); a.or_("v0", "v0", "v1"); a.and_("v0", "v0", "v1"); a.xor("v0", "v0", "v1")
    a.lwc1("f0", 0x40, "s0"); a.swc1("f1", 0x44, "s0"); a.add_s("f0", "f0", "f20"); a.sub_s("f1", "f1", "f2")
    a.mul_s("f2", "f2", "f0"); a.div_s("f3", "f1", "f2"); a.mov_s("f12", "f20"); a.neg_s("f4", "f4")
    a.c_lt_s("f2", "f0"); a.c_le_s("f2", "f0"); a.cvt_s_w("f0", "f0"); a.cvt_w_s("f1", "f1")
    a.mtc1("at", "f0"); a.mfc1("v0", "f1"); a.ld("ra", 0, "sp"); a.sd("ra", 0, "sp"); a.lq("a0", 0x40, "t0"); a.sq("t0", 0x10, "t1")
    a.por("a0", "zero", "s3"); a.jr("ra"); a.nop()
    a.beq("t0", "t1", "top"); a.nop(); a.bnez("t0", "top"); a.nop(); a.bltz("t0", "top"); a.nop(); a.bgez("t0", "top"); a.nop()
    a.bc1t("top"); a.nop(); a.bc1f("top"); a.nop(); a.j(0x2A3F10); a.nop(); a.jal(0x16D668); a.nop(); a.jalr("t9"); a.nop()
    data = a.assemble()
    got = dis(data, 0x4A5000)
    exp = ["addiu $t0, $a0, -4", "lw $v0, 0x94($s0)", "sw $t1, -8($sp)", "lbu $t2, 0x9a($s0)", "sb $zero, ($t3)",
           "lui $t4, 0x4a", "ori $t4, $t4, 0x1234", "andi $t5, $t5, 7", "sll $t6, $t6, 5", "srl $t6, $t6, 2",
           "sra $t6, $t6, 1", "addu $t7, $t6, $t5", "subu $t7, $t6, $t5", "slt $v1, $t0, $t1", "sltu $v1, $t0, $t1",
           "slti $v1, $t0, 3", "sltiu $v1, $t0, 3", "move $a0, $s0", "or $v0, $v0, $v1", "and $v0, $v0, $v1",
           "xor $v0, $v0, $v1", "lwc1 $f0, 0x40($s0)", "swc1 $f1, 0x44($s0)", "add.s $f0, $f0, $f20",
           "sub.s $f1, $f1, $f2", "mul.s $f2, $f2, $f0", "div.s $f3, $f1, $f2", "mov.s $f12, $f20", "neg.s $f4, $f4",
           "c.lt.s $f2, $f0", "c.le.s $f2, $f0", "cvt.s.w $f0, $f0", "cvt.w.s $f1, $f1", "mtc1 $at, $f0",
           "mfc1 $v0, $f1", "ld $ra, ($sp)", "sd $ra, ($sp)"]
    for g, e in zip(got, exp):
        assert g.replace("c.olt", "c.lt").replace("c.ole", "c.le") == e, (g, e)
    # lq/sq/por are EE-only: check the raw words
    w = struct.unpack("<%dI" % (len(data) // 4), data)
    i = len(exp)
    assert w[i] == (0x1E << 26) | (8 << 21) | (4 << 16) | 0x40          # lq a0,0x40(t0)
    assert w[i + 1] == (0x1F << 26) | (9 << 21) | (8 << 16) | 0x10      # sq t0,0x10(t1)
    assert w[i + 2] == 0x701324A9                                       # por a0,zero,s3 (seen in Dominator)
    rest = got[i + 3:]
    assert rest[0] == "jr $ra" and rest[2].startswith("beq $t0, $t1, 0x4a5000") and rest[4] == "bnez $t0, 0x4a5000"
    assert rest[6] == "bltz $t0, 0x4a5000" and rest[8] == "bgez $t0, 0x4a5000"
    assert rest[10] == "bc1t 0x4a5000" and rest[12] == "bc1f 0x4a5000"
    assert rest[14] == "j 0x2a3f10" and rest[16] == "jal 0x16d668" and rest[18] == "jalr $t9"


def test_interpreter_basics():
    a = Asm(0x4A5000)
    a.li("t0", 5); a.li("t1", 0)
    a.label("loop"); a.addu("t1", "t1", "t0"); a.addiu("t0", "t0", -1); a.bnez("t0", "loop"); a.nop()
    a.lif("f0", 1.5); a.lif("f1", 2.0); a.mul_s("f2", "f0", "f1"); a.c_lt_s("f0", "f1"); a.bc1f("bad"); a.nop()
    a.la("t2", 0x4A6000); a.swc1("f2", 0, "t2"); a.sw("t1", 4, "t2"); a.move("s7", "ra"); a.jal(0x123450); a.li("a0", 7); a.move("ra", "s7")
    a.jr("ra"); a.nop()
    a.label("bad"); a.sw("zero", 4, "t2"); a.jr("ra"); a.nop()
    cpu = Cpu()
    cpu.m.write(0x4A5000, a.assemble())
    called = []
    def stub(c):
        called.append(c.gr(4))
    cpu.stubs[0x123450] = stub
    # the stub returns to $ra, which jal set; the outer return is the sentinel
    cpu.g[29] = 0x70000
    a2 = Asm(0x4A4F00); a2.jal(0x4A5000); a2.nop(); a2.label("end"); a2.j("end"); a2.nop()
    cpu.m.write(0x4A4F00, a2.assemble())
    cpu.call(0x4A5000)
    assert cpu.m.f32(0x4A6000) == 3.0 and cpu.m.u32(0x4A6004) == 15 and called == [7]
