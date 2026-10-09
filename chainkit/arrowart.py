"""ChainKit's own arrow: Revenge's chevron slash (HUD texture chev_sml) repainted so it reads well when ChainKit tints it.

Revenge draws its 16x8 chev_sml as a black, mostly transparent slash (alpha at most 0x2A of 0x80) - tinted cyan by
ChainKit it stays black and almost invisible. Here the slash's own shape (its alpha) is taken from the user's
GLOBAL.TXD, rescaled to the 32x32 TalkIcon / Boost_Arrow format, painted white (so the tint gives the colour) with its
soft edges stretched to fully opaque, and stored with a 16-step alpha ramp - the same format as Dominator's
Boost_Arrow, which the game shows correctly. Nothing of the game is shipped: the art is made from the user's disc.
"""
from . import assets, ps2tex

SOURCE = "chev_sml"
# display size of one arrow quad in the HUD (cave.DESIGN aw x ah, design units)
QUAD_W, QUAD_H = 13.0, 16.0


def chevron_mask(revenge_txd):
    """The slash as alpha 0..1 rows (16x8), from GLOBAL.TXD."""
    o, s = assets.txd_records(revenge_txd)[SOURCE]
    tr = ps2tex.TexRecord(revenge_txd[o:o + s])
    img, clut = tr.decode()
    amax = max(c[3] for c in clut) or 1
    return [[clut[i][3] / amax for i in row] for row in img]


def _sample(mask, x, y):
    """Bilinear sample of the mask at pixel-centre coordinates (outside = 0)."""
    h, w = len(mask), len(mask[0])
    x -= 0.5
    y -= 0.5
    x0, y0 = int(x // 1), int(y // 1)
    fx, fy = x - x0, y - y0

    def px(xx, yy):
        return mask[yy][xx] if 0 <= xx < w and 0 <= yy < h else 0.0
    return ((px(x0, y0) * (1 - fx) + px(x0 + 1, y0) * fx) * (1 - fy)
            + (px(x0, y0 + 1) * (1 - fx) + px(x0 + 1, y0 + 1) * fx) * fy)


def repaint(mask, size=32, fill=0.9, keep_aspect=False, ss=4):
    """32x32 alpha 0..1 of the slash for an arrow quad (QUAD_W x QUAD_H on screen).
    keep_aspect: the slash keeps Revenge's proportions on screen (shorter); else it fills the quad's height."""
    mh, mw = len(mask), len(mask[0])
    tex_x, tex_y = QUAD_W / size, QUAD_H / size            # screen units per texel
    box_w, box_h = QUAD_W * fill, QUAD_H * fill
    if keep_aspect:
        s = min(box_w / mw, box_h / mh)
        sx = sy = s
    else:
        sx, sy = box_w / mw, box_h / mh                    # fill the quad (slash a little steeper)
    off_x, off_y = (QUAD_W - mw * sx) / 2, (QUAD_H - mh * sy) / 2
    out = []
    for ty in range(size):
        row = []
        for tx in range(size):
            acc = 0.0
            for k in range(ss):
                for j in range(ss):
                    ux = (tx + (j + 0.5) / ss) * tex_x
                    uy = (ty + (k + 0.5) / ss) * tex_y
                    acc += _sample(mask, (ux - off_x) / sx, (uy - off_y) / sy)
            row.append(acc / (ss * ss))
        out.append(row)
    # the original's soft edge ends far below opaque: stretch so the body is fully opaque, edges stay soft
    peak = max(max(r) for r in out) or 1.0
    return [[min(1.0, v / (peak * 0.7)) for v in r] for r in out]


RAMP = [0, 4, 0x0C, 0x14, 0x1C, 0x24, 0x2C, 0x34, 0x3C, 0x44, 0x4C, 0x54, 0x5C, 0x66, 0x72, 0x80]   # PS2 alpha


def encode(alpha, template_rec):
    """The TalkIcon-format record with this alpha (white, 16-step alpha ramp CLUT)."""
    tr = ps2tex.TexRecord(template_rec)
    img = [[min(range(16), key=lambda i: abs(RAMP[i] - a * 0x80)) for a in row] for row in alpha]
    clut = [(0xFF, 0xFF, 0xFF, a) for a in RAMP]
    return tr.encode(img, clut)


def chainkit_record(revenge_txd, keep_aspect=False):
    """TalkIcon record of GLOBAL.TXD with ChainKit's arrow (same header, new pixels + CLUT)."""
    ro, rs = assets.txd_records(revenge_txd)[assets.TARGET]
    return encode(repaint(chevron_mask(revenge_txd), keep_aspect=keep_aspect), revenge_txd[ro:ro + rs])


def is_chainkit(txd, original_txd=None):
    """TalkIcon holds ChainKit's arrow (white 16-step ramp CLUT; with the original GLOBAL.TXD: exactly ours)."""
    ro, rs = assets.txd_records(txd)[assets.TARGET]
    tr = ps2tex.TexRecord(txd[ro:ro + rs])
    _, clut = tr.decode()
    if clut != [(0xFF, 0xFF, 0xFF, a) for a in RAMP]:
        return False
    return original_txd is None or txd[ro:ro + rs] == chainkit_record(original_txd)


def merge(revenge_txd, keep_aspect=False):
    """GLOBAL.TXD with ChainKit's arrow in place of TalkIcon (like assets.merge_arrow with Dominator's)."""
    ro, rs = assets.txd_records(revenge_txd)[assets.TARGET]
    out = bytearray(revenge_txd)
    out[ro:ro + rs] = chainkit_record(revenge_txd, keep_aspect)
    return bytes(out)
