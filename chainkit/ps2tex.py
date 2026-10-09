"""PS2 texture records of Burnout's GLOBAL.TXD: decode to an image and encode back (byte-exact).

A record holds a ready GS upload: the bitmap is sent with an IMAGE transfer in one pixel format (BITBLTBUF.DPSM,
e.g. PSMCT16) but drawn in another (TEX0.PSM, e.g. PSMT4), so the bytes in the file are the GS memory layout of one
format read as the other. This module models GS local memory with PCSX2's swizzle tables (pcsx2/GS/GSTables.cpp:
block and column tables of PSMCT32 / PSMCT16 / PSMT4) to translate between the two.

Record layout (shared with the car textures):
  +0x04 bitmap offset, +0x08 CLUT data offset, +0x0C/+0x10 width/height, +0x14 bits per pixel, +0x3C GS TEX0,
  +0x100 upload list (2 x 0x40: BITBLTBUF for the bitmap / the CLUT), bitmap at +0x04 behind its GIF A+D block
  (TRXREG = transfer rectangle), CLUT data at +0x08 behind its own A+D block.
"""
import struct

# ---------------------------------------------------------------------------------------------- GS swizzle tables
_BLOCK32 = [[0, 1, 4, 5, 16, 17, 20, 21], [2, 3, 6, 7, 18, 19, 22, 23],
            [8, 9, 12, 13, 24, 25, 28, 29], [10, 11, 14, 15, 26, 27, 30, 31]]
_BLOCK16 = [[0, 2, 8, 10], [1, 3, 9, 11], [4, 6, 12, 14], [5, 7, 13, 15],
            [16, 18, 24, 26], [17, 19, 25, 27], [20, 22, 28, 30], [21, 23, 29, 31]]
_BLOCK4 = _BLOCK16
_COL32 = [[0, 1, 4, 5, 8, 9, 12, 13], [2, 3, 6, 7, 10, 11, 14, 15], [16, 17, 20, 21, 24, 25, 28, 29],
          [18, 19, 22, 23, 26, 27, 30, 31], [32, 33, 36, 37, 40, 41, 44, 45], [34, 35, 38, 39, 42, 43, 46, 47],
          [48, 49, 52, 53, 56, 57, 60, 61], [50, 51, 54, 55, 58, 59, 62, 63]]
_COL16 = [[0, 2, 8, 10, 16, 18, 24, 26, 1, 3, 9, 11, 17, 19, 25, 27],
          [4, 6, 12, 14, 20, 22, 28, 30, 5, 7, 13, 15, 21, 23, 29, 31],
          [32, 34, 40, 42, 48, 50, 56, 58, 33, 35, 41, 43, 49, 51, 57, 59],
          [36, 38, 44, 46, 52, 54, 60, 62, 37, 39, 45, 47, 53, 55, 61, 63],
          [64, 66, 72, 74, 80, 82, 88, 90, 65, 67, 73, 75, 81, 83, 89, 91],
          [68, 70, 76, 78, 84, 86, 92, 94, 69, 71, 77, 79, 85, 87, 93, 95],
          [96, 98, 104, 106, 112, 114, 120, 122, 97, 99, 105, 107, 113, 115, 121, 123],
          [100, 102, 108, 110, 116, 118, 124, 126, 101, 103, 109, 111, 117, 119, 125, 127]]


# Literal copy of PCSX2's columnTable4 (rows 4..15 differ from a simple pattern, so no shortcut is taken).
_COL4 = [
    [0, 8, 32, 40, 64, 72, 96, 104, 2, 10, 34, 42, 66, 74, 98, 106, 4, 12, 36, 44, 68, 76, 100, 108, 6, 14, 38, 46, 70, 78, 102, 110],
    [16, 24, 48, 56, 80, 88, 112, 120, 18, 26, 50, 58, 82, 90, 114, 122, 20, 28, 52, 60, 84, 92, 116, 124, 22, 30, 54, 62, 86, 94, 118, 126],
    [65, 73, 97, 105, 1, 9, 33, 41, 67, 75, 99, 107, 3, 11, 35, 43, 69, 77, 101, 109, 5, 13, 37, 45, 71, 79, 103, 111, 7, 15, 39, 47],
    [81, 89, 113, 121, 17, 25, 49, 57, 83, 91, 115, 123, 19, 27, 51, 59, 85, 93, 117, 125, 21, 29, 53, 61, 87, 95, 119, 127, 23, 31, 55, 63],
    [192, 200, 224, 232, 128, 136, 160, 168, 194, 202, 226, 234, 130, 138, 162, 170, 196, 204, 228, 236, 132, 140, 164, 172, 198, 206, 230, 238, 134, 142, 166, 174],
    [208, 216, 240, 248, 144, 152, 176, 184, 210, 218, 242, 250, 146, 154, 178, 186, 212, 220, 244, 252, 148, 156, 180, 188, 214, 222, 246, 254, 150, 158, 182, 190],
    [129, 137, 161, 169, 193, 201, 225, 233, 131, 139, 163, 171, 195, 203, 227, 235, 133, 141, 165, 173, 197, 205, 229, 237, 135, 143, 167, 175, 199, 207, 231, 239],
    [145, 153, 177, 185, 209, 217, 241, 249, 147, 155, 179, 187, 211, 219, 243, 251, 149, 157, 181, 189, 213, 221, 245, 253, 151, 159, 183, 191, 215, 223, 247, 255],
    [256, 264, 288, 296, 320, 328, 352, 360, 258, 266, 290, 298, 322, 330, 354, 362, 260, 268, 292, 300, 324, 332, 356, 364, 262, 270, 294, 302, 326, 334, 358, 366],
    [272, 280, 304, 312, 336, 344, 368, 376, 274, 282, 306, 314, 338, 346, 370, 378, 276, 284, 308, 316, 340, 348, 372, 380, 278, 286, 310, 318, 342, 350, 374, 382],
    [321, 329, 353, 361, 257, 265, 289, 297, 323, 331, 355, 363, 259, 267, 291, 299, 325, 333, 357, 365, 261, 269, 293, 301, 327, 335, 359, 367, 263, 271, 295, 303],
    [337, 345, 369, 377, 273, 281, 305, 313, 339, 347, 371, 379, 275, 283, 307, 315, 341, 349, 373, 381, 277, 285, 309, 317, 343, 351, 375, 383, 279, 287, 311, 319],
    [448, 456, 480, 488, 384, 392, 416, 424, 450, 458, 482, 490, 386, 394, 418, 426, 452, 460, 484, 492, 388, 396, 420, 428, 454, 462, 486, 494, 390, 398, 422, 430],
    [464, 472, 496, 504, 400, 408, 432, 440, 466, 474, 498, 506, 402, 410, 434, 442, 468, 476, 500, 508, 404, 412, 436, 444, 470, 478, 502, 510, 406, 414, 438, 446],
    [385, 393, 417, 425, 449, 457, 481, 489, 387, 395, 419, 427, 451, 459, 483, 491, 389, 397, 421, 429, 453, 461, 485, 493, 391, 399, 423, 431, 455, 463, 487, 495],
    [401, 409, 433, 441, 465, 473, 497, 505, 403, 411, 435, 443, 467, 475, 499, 507, 405, 413, 437, 445, 469, 477, 501, 509, 407, 415, 439, 447, 471, 479, 503, 511],
]

# psm: (page width, page height, block table, column table, bits per pixel)
PSMCT32, PSMCT16, PSMT4 = 0x00, 0x02, 0x14
_FMT = {PSMCT32: (64, 32, _BLOCK32, _COL32, 32), PSMCT16: (64, 64, _BLOCK16, _COL16, 16),
        PSMT4: (128, 128, _BLOCK4, _COL4, 4)}


def gs_bit_address(psm, x, y, bp, bw):
    """Bit address of pixel (x, y) in GS local memory (bp in 256-byte blocks, bw in 64-pixel units)."""
    pw, ph, btab, ctab, bpp = _FMT[psm]
    ch, cw = len(ctab), len(ctab[0])
    pages_per_row = max(1, bw * 64 // pw)
    page = (y // ph) * pages_per_row + x // pw
    sx, sy = x % pw, y % ph
    px = btab[sy // ch][sx // cw] * (ch * cw) + ctab[sy % ch][sx % cw]
    return bp * 256 * 8 + page * 8192 * 8 + px * bpp


# ---------------------------------------------------------------------------------------------- records
class TexRecord:
    """The upload description of one GLOBAL.TXD record (offsets relative to the record)."""

    def __init__(self, rec):
        self.rec = bytes(rec)
        r = self.rec
        self.bitmap_off, self.clut_off, self.w, self.h, self.bpp = struct.unpack_from("<5I", r, 4)
        tex0 = struct.unpack_from("<Q", r, 0x3C)[0]
        self.psm = (tex0 >> 20) & 0x3F
        self.tbw = (tex0 >> 14) & 0x3F
        # upload list: entry 0 = bitmap, entry 1 = CLUT; each holds an A+D BITBLTBUF value at +0x20
        self.bitblt = [struct.unpack_from("<Q", r, 0x110 + 0x40 * k + 0x20)[0] for k in range(2)]
        self.trx = [self._trxreg(self.bitmap_off), self._trxreg(self.clut_off)]
        if self.psm != PSMT4 or self.bpp != 4:
            raise ValueError("only 4-bit (PSMT4) textures are supported, not psm %#x" % self.psm)

    def _trxreg(self, data_off):
        a_d = data_off - 0x50                             # GIF A+D block (4 registers) right before the data
        rrw, rrh = struct.unpack_from("<2I", self.rec, a_d + 0x20)
        return rrw, rrh

    def _upload_psm(self, k):
        return (self.bitblt[k] >> 56) & 0x3F, max(1, (self.bitblt[k] >> 48) & 0x3F)

    def bitmap_map(self):
        """[(byte offset in the record, nibble 0/1, x, y)] for every texture pixel."""
        dpsm, dbw = self._upload_psm(0)
        rrw, rrh = self.trx[0]
        bpp = _FMT[dpsm][4]
        where = {}                                         # GS bit address -> record bit position
        for y in range(rrh):
            for x in range(rrw):
                g = gs_bit_address(dpsm, x, y, 0, dbw)
                f = (self.bitmap_off * 8) + (y * rrw + x) * bpp
                for b in range(bpp):
                    where[g + b] = f + b
        out = []
        for y in range(self.h):
            for x in range(self.w):
                g = gs_bit_address(PSMT4, x, y, 0, self.tbw)
                fbit = where[g]                            # the 4 bits of this pixel are contiguous here
                assert all(where[g + k] == fbit + k for k in range(4))
                out.append((fbit // 8, (fbit % 8) // 4, x, y))
        return out

    def decode(self):
        """(indices[h][w], clut[16] as (r, g, b, a) with PS2 alpha 0..0x80)."""
        img = [[0] * self.w for _ in range(self.h)]
        for off, nib, x, y in self.bitmap_map():
            b = self.rec[off]
            img[y][x] = (b >> 4) if nib else (b & 15)
        clut = [tuple(self.rec[self.clut_off + 4 * k:self.clut_off + 4 * k + 4]) for k in range(16)]
        return img, clut

    def encode(self, img, clut):
        """A copy of the record with these indices and CLUT (everything else unchanged)."""
        out = bytearray(self.rec)
        for off, nib, x, y in self.bitmap_map():
            v = img[y][x] & 15
            out[off] = (out[off] & 0x0F) | (v << 4) if nib else (out[off] & 0xF0) | v
        for k, c in enumerate(clut):
            out[self.clut_off + 4 * k:self.clut_off + 4 * k + 4] = bytes(c)
        return bytes(out)


def to_rgba(img, clut):
    """RGBA rows (8-bit alpha) of a decoded texture."""
    rows = []
    for row in img:
        r = []
        for i in row:
            cr, cg, cb, ca = clut[i]
            r.append((cr, cg, cb, min(255, ca * 255 // 128)))
        rows.append(r)
    return rows
