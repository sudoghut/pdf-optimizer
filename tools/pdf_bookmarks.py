#!/usr/bin/env python
"""Copy the outline (bookmarks) from one PDF to another.

OCR engines routinely drop the outline: ABBYY discarded all 135 entries of the
case-study book. The two files still have identical page order, so the outline
transplants directly -- level, title, target page and target position all carry
over.

  python tools/pdf_bookmarks.py --show file.pdf
  python tools/pdf_bookmarks.py --from original.pdf --to opt.pdf [--out new.pdf]

Without --out the target is updated in place (via a temp file, then replace).
"""
import argparse
import os
import shutil
import sys
import tempfile

import fitz


def show(path):
    d = fitz.open(path)
    toc = d.get_toc(simple=False)
    print("%s: %d outline entries, %d pages" % (os.path.basename(path), len(toc), d.page_count))
    for lvl, title, page, *rest in toc:
        dest = rest[0] if rest else {}
        pos = dest.get("to") if isinstance(dest, dict) else None
        print("  %s%s  -> page %d%s"
              % ("    " * (lvl - 1), title, page,
                 "" if pos is None else "  y=%.1f" % pos.y))
    return toc


def transplant(src_path, dst_path, out_path=None):
    src, dst = fitz.open(src_path), fitz.open(dst_path)
    toc = src.get_toc(simple=False)
    if not toc:
        print("source has no outline, nothing to do")
        return 1
    print("source  : %s  (%d entries, %d pages)"
          % (os.path.basename(src_path), len(toc), src.page_count))
    print("target  : %s  (%d existing entries, %d pages)"
          % (os.path.basename(dst_path), len(dst.get_toc()), dst.page_count))

    if src.page_count != dst.page_count:
        print("REFUSING: page counts differ (%d vs %d) -- destinations would be wrong"
              % (src.page_count, dst.page_count))
        return 2

    # Destinations must be rebuilt, not copied. A named destination
    # (kind == LINK_NAMED) resolves through the SOURCE document's /Names tree;
    # handed to another file it resolves to nothing and set_toc silently
    # degrades it to kind 0 / page -1 -- bookmarks that look present but jump
    # nowhere. Re-express every entry as an explicit target in this document.
    rebuilt, kept, dropped = [], 0, 0
    for lvl, title, page, *rest in toc:
        if not (1 <= page <= dst.page_count):
            dropped += 1
            continue
        src_dest = rest[0] if rest and isinstance(rest[0], dict) else {}
        pos = src_dest.get("to")
        if src_dest.get("kind") == fitz.LINK_GOTO and pos is not None:
            # a real explicit destination: keep the position, clamp to the
            # target page (MediaBox heights can differ by a fraction of a point)
            h = dst.load_page(page - 1).rect.height
            y = min(pos.y, h)
            rebuilt.append([lvl, title, page,
                            {"kind": fitz.LINK_GOTO, "page": page - 1,
                             "to": fitz.Point(pos.x, y),
                             "zoom": src_dest.get("zoom", 0)}])
            kept += 1
        else:
            # named destination / Fit view / anything unresolvable: aim at the
            # top of the page, which is what "Fit" shows anyway
            rebuilt.append([lvl, title, page])
    print("destinations: %d explicit kept, %d rebuilt as page targets, %d dropped"
          % (kept, len(rebuilt) - kept, dropped))

    dst.set_toc(rebuilt)

    in_place = out_path is None
    if in_place:
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(dst_path)))
        os.close(fd)
        target = tmp
    else:
        target = out_path

    dst.save(target, garbage=3, deflate=True)
    dst.close()
    src.close()

    if in_place:
        shutil.move(target, dst_path)
        target = dst_path

    # Counting entries is not enough: broken destinations still count. Check
    # that every bookmark resolves to the page the source pointed at.
    check = fitz.open(target)
    got = check.get_toc()
    want = [[lvl, title, page] for lvl, title, page, *_ in rebuilt]
    n = len(got)
    bad = [(w, g) for w, g in zip(want, got) if g[2] != w[2]]
    print("written : %s  (%.2f MB, %d outline entries)"
          % (os.path.basename(target), os.path.getsize(target) / 1048576, n))
    if n != len(rebuilt):
        print("FAIL: expected %d entries, got %d" % (len(rebuilt), n))
        return 3
    if bad:
        print("FAIL: %d bookmark(s) point at the wrong page, e.g. %r -> got page %d"
              % (len(bad), bad[0][0][1], bad[0][1][2]))
        return 4
    print("check   : all %d bookmarks resolve to the intended page "
          "(levels %d..%d, pages %d..%d)"
          % (n, min(g[0] for g in got), max(g[0] for g in got),
             min(g[2] for g in got), max(g[2] for g in got)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", metavar="PDF", help="print the outline of a file and exit")
    ap.add_argument("--from", dest="src", help="PDF to copy the outline from")
    ap.add_argument("--to", dest="dst", help="PDF to copy the outline into")
    ap.add_argument("--out", help="write result here instead of updating --to in place")
    a = ap.parse_args()

    if a.show:
        show(a.show)
        return 0
    if not (a.src and a.dst):
        ap.error("need --show, or both --from and --to")
    return transplant(a.src, a.dst, a.out)


if __name__ == "__main__":
    sys.exit(main())
