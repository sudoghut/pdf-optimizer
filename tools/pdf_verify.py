#!/usr/bin/env python
"""Verify an optimized PDF against the file it was derived from.

Checks the three things that actually break when you rewrite image streams:
  1. page count / page geometry
  2. the extracted text layer (OCR output must survive byte-for-byte)
  3. rendered pixels -- catches inverted CCITT (BlackIs1 wrong), misalignment
     and dropped images, which no structural check would notice
"""
import argparse
import sys
import numpy as np
import fitz


def render(doc, pno, dpi=100):
    p = doc.load_page(pno)
    pm = p.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    return np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference")
    ap.add_argument("candidate")
    ap.add_argument("--pages", default="", help="comma list of 1-based pages to render")
    ap.add_argument("--dpi", type=int, default=100)
    a = ap.parse_args()

    ref, cand = fitz.open(a.reference), fitz.open(a.candidate)
    ok = True

    print("pages: %d vs %d" % (ref.page_count, cand.page_count))
    if ref.page_count != cand.page_count:
        print("  FAIL: page count differs")
        ok = False

    # ---- geometry
    geom_bad = []
    for i in range(min(ref.page_count, cand.page_count)):
        ra, ca = ref.load_page(i).rect, cand.load_page(i).rect
        if abs(ra.width - ca.width) > 0.5 or abs(ra.height - ca.height) > 0.5:
            geom_bad.append((i + 1, tuple(ra), tuple(ca)))
    print("geometry mismatches: %d" % len(geom_bad))
    for g in geom_bad[:5]:
        print("   page %d %s vs %s" % g)
    if geom_bad:
        ok = False

    # ---- text layer
    diff_pages, ref_chars, cand_chars = [], 0, 0
    for i in range(min(ref.page_count, cand.page_count)):
        ta = ref.load_page(i).get_text("text")
        tb = cand.load_page(i).get_text("text")
        ref_chars += len(ta)
        cand_chars += len(tb)
        if ta != tb:
            diff_pages.append(i + 1)
    print("text: %s chars (ref) vs %s chars (cand); pages differing: %d"
          % (f"{ref_chars:,}", f"{cand_chars:,}", len(diff_pages)))
    if diff_pages:
        print("   first differing pages: %s" % diff_pages[:10])
        ok = False

    # ---- pixels
    pages = [int(x) for x in a.pages.split(",") if x.strip()] or \
            [1, 14, 15, 16, 100, 300, 500, 607, 608]
    pages = [p for p in pages if 1 <= p <= min(ref.page_count, cand.page_count)]
    print("\nrendered comparison @ %d dpi" % a.dpi)
    print("%6s %10s %10s %9s %9s  %s" %
          ("page", "ref_mean", "cand_mean", "MAE", "%pix>32", "verdict"))
    for p in pages:
        A, B = render(ref, p - 1, a.dpi), render(cand, p - 1, a.dpi)
        if A.shape != B.shape:
            h = min(A.shape[0], B.shape[0]); w = min(A.shape[1], B.shape[1])
            A, B = A[:h, :w], B[:h, :w]
        d = np.abs(A.astype(np.int16) - B.astype(np.int16))
        mae = d.mean()
        big = 100.0 * (d > 32).mean()
        # an inverted page shows up as a huge mean-brightness flip
        inverted = abs((255 - A.mean()) - B.mean()) < abs(A.mean() - B.mean()) - 40
        verdict = "INVERTED!" if inverted else ("ok" if big < 3.0 else "CHECK (%.1f%% differ)" % big)
        if inverted or big >= 3.0:
            ok = False
        print("%6d %10.2f %10.2f %9.3f %8.2f%%  %s"
              % (p, A.mean(), B.mean(), mae, big, verdict))

    print("\n%s" % ("PASS" if ok else "FAIL"))
    if not ok:
        print("NOTE: if the reference is itself a re-encoded (e.g. grayscale JPEG)"
              " version of\n"
              "      a bilevel scan, edge pixels legitimately differ -- the crisp"
              " 1-bit page\n"
              "      is the more faithful one. Settle those pages against the TRUE"
              " source\n"
              "      instead, by comparing decoded bitmaps rather than renders.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
