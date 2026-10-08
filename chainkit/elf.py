"""Minimal ELF access for the PS2 boot executable + PCSX2 CRC helpers (shared with MusicKit, MIT)."""
import struct


def crc(data):
    """PCSX2 game CRC: XOR of every little-endian 32-bit word of the ELF file."""
    import numpy as np
    n = len(data) // 4 * 4
    return int(np.bitwise_xor.reduce(np.frombuffer(bytes(data[:n]), dtype="<u4"))) if n else 0


class Elf:
    def __init__(self, data):
        self.d = bytearray(data)
        if self.d[:4] != b"\x7fELF":
            raise ValueError("not an ELF file")
        self.phoff = struct.unpack_from("<I", self.d, 0x1C)[0]
        self.phnum = struct.unpack_from("<H", self.d, 0x2C)[0]
        self.shoff = struct.unpack_from("<I", self.d, 0x20)[0]
        self.shnum = struct.unpack_from("<H", self.d, 0x30)[0]

    def phdrs(self):
        return [list(struct.unpack_from("<8I", self.d, self.phoff + 32 * i)) for i in range(self.phnum)]

    def set_phdr(self, i, ph):
        struct.pack_into("<8I", self.d, self.phoff + 32 * i, *ph)

    def sections(self):
        return [list(struct.unpack_from("<10I", self.d, self.shoff + 40 * i)) for i in range(self.shnum)]

    def file_offset(self, va):
        for ph in self.phdrs():
            if ph[0] == 1 and ph[2] <= va < ph[2] + ph[4]:
                return ph[1] + va - ph[2]
        raise KeyError(hex(va))

    def r32(self, va):
        return struct.unpack_from("<I", self.d, self.file_offset(va))[0]

    def w32(self, va, v):
        struct.pack_into("<I", self.d, self.file_offset(va), v)

    def content_end(self):
        end = self.shoff + self.shnum * 40
        for sh in self.sections():
            if sh[1] != 8:
                end = max(end, sh[4] + sh[5])
        for ph in self.phdrs():
            end = max(end, ph[1] + ph[4])
        return end


def _fix_crc(data, target, appended):
    """Make crc(data) == target via a compensation word after the ELF content (appended if needed)."""
    out = bytearray(data)
    if len(out) % 4:
        out += b"\0" * (4 - len(out) % 4)
    if not appended:
        out += b"\0\0\0\0"
    struct.pack_into("<I", out, len(out) - 4, 0)
    struct.pack_into("<I", out, len(out) - 4, crc(out) ^ target)
    assert crc(out) == target
    return bytes(out)


