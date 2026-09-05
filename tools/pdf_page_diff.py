#!/usr/bin/env python
"""Per-page image-encoding diff between two PDFs with the same page count.

Shows which pages changed codec / colorspace / bit-depth and what that cost.
"""
import sys
import os
import collections
import pikepdf


def collect_xobjects(res, seen, depth=0):
    """Yield every image XObject reachable from a /Resources dict.

    ABBYY wraps page content in Form XObjects, so a non-recursive walk of
    page /Resources finds nothing.
    """
    if depth > 8 or res is None:
        return
    try:
        xo = res.get("/XObject", None)
    except Exception:
        return
    if not xo:
        return
    for _name, x in xo.items():
        try:
            oid = x.objgen
        except Exception:
            oid = None
        if oid and oid in seen:
            continue
        if oid:
            seen.add(oid)
        try:
            st = str(x.get("/Subtype"))
        except Exception:
            continue
        if st == "/Image":
            yield x
        elif st == "/Form":
            yield from collect_xobjects(x.get("/Resources", None), seen, depth + 1)


def page_images(pdf):
    """[(page_no, [(w,h,cs,bpc,filter,rawbytes), ...]), ...]"""
    out = []
    for i, page in enumerate(pdf.pages, 1):
        imgs = []
        seen = set()
        try:
            res = page.obj.get("/Resources", None)
        except Exception:
            res = None
        for x in collect_xobjects(res, seen):
            try:
                f = x.get("/Filter")
                fs = "+".join(str(v) for v in f) if isinstance(f, pikepdf.Array) else str(f)
                cs = x.get("/ColorSpace")
                if isinstance(cs, pikepdf.Array):
                    css = str(cs[0])
                    if css == "/ICCBased":
                        try:
                            css = "ICC(N=%s)" % cs[1].get("/N")
                        except Exception:
                            css = "ICCBased"
                else:
                    css = str(cs) if cs is not None else "-"
                imgs.append((int(x.get("/Width")), int(x.get("/Height")), css,
                             int(x.get("/BitsPerComponent", 1)), fs,
                             len(x.read_raw_bytes())))
            except Exception:
                continue
        out.append((i, imgs))
    return out


def sig(imgs):
    return " | ".join("%s %s %dbpc" % (f.replace("/", "").replace("Decode", ""), cs, b)
                      for (_w, _h, cs, b, f, _n) in imgs) or "(no image)"


def main(a, b):
    pa, pb = pikepdf.open(a), pikepdf.open(b)
    A, B = page_images(pa), page_images(pb)
    print("pages: %d vs %d" % (len(A), len(B)))

    tot_a = sum(n for _, im in A for *_r, n in im)
    tot_b = sum(n for _, im in B for *_r, n in im)
    print("image bytes: %s -> %s  (delta %+s)"
          % (f"{tot_a:,}", f"{tot_b:,}", f"{tot_b - tot_a:,}"))
    print()

    trans = collections.defaultdict(lambda: [0, 0, 0])   # (siga,sigb) -> [pages, bytes_a, bytes_b]
    for (ia, ima), (ib, imb) in zip(A, B):
        sa, sb = sig(ima), sig(imb)
        na = sum(n for *_r, n in ima)
        nb = sum(n for *_r, n in imb)
        k = (sa, sb)
        trans[k][0] += 1
        trans[k][1] += na
        trans[k][2] += nb

    print("%-6s %14s %14s %14s   TRANSITION" % ("PAGES", "BYTES BEFORE", "BYTES AFTER", "DELTA"))
    print("-" * 110)
    for (sa, sb), (c, na, nb) in sorted(trans.items(), key=lambda kv: -(kv[1][2] - kv[1][1])):
        print("%-6d %14s %14s %14s" % (c, f"{na:,}", f"{nb:,}", f"{nb-na:+,}"))
        print("       BEFORE: %s" % sa)
        print("       AFTER : %s" % sb)
    print()

    # which page numbers became JPEG
    jpeg_pages = [ib for (ib, imb) in B if any("DCT" in f for *_r, f, _n in imb)]
    print("pages containing JPEG in AFTER (%d): %s%s"
          % (len(jpeg_pages), jpeg_pages[:60], " ..." if len(jpeg_pages) > 60 else ""))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
