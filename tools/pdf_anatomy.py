#!/usr/bin/env python
"""Object-level size accounting for a PDF.

Answers "where did the bytes actually go?" by attributing every byte of every
object to a category (image data, embedded fonts, content streams, structure
tree, ...) instead of guessing from page-level tools.
"""
import sys
import collections
import pikepdf


def raw_len(obj):
    """Bytes this object occupies in the file (compressed / as-stored)."""
    try:
        return len(obj.read_raw_bytes())
    except Exception:
        pass
    try:
        return len(pikepdf.unparse(obj))
    except Exception:
        return 0


def filters_of(d):
    f = d.get("/Filter")
    if f is None:
        return ""
    if isinstance(f, pikepdf.Array):
        return "+".join(str(x) for x in f)
    return str(f)


def categorize(obj):
    """Return (category, detail) for one indirect object."""
    if not isinstance(obj, pikepdf.Object):
        return "other", ""
    try:
        t = str(obj.get("/Type")) if "/Type" in obj else ""
        st = str(obj.get("/Subtype")) if "/Subtype" in obj else ""
    except Exception:
        return "other", ""

    if st == "/Image":
        return "image", filters_of(obj)
    if st == "/Form":
        return "form-xobject", filters_of(obj)
    if t == "/Font" or st in ("/Type0", "/Type1", "/TrueType", "/CIDFontType0", "/CIDFontType2"):
        return "font-dict", st
    if t == "/FontDescriptor":
        return "font-descriptor", ""
    if st in ("/CIDFontType0C", "/CIDFontType2", "/Type1C", "/OpenType") or t == "/FontFile2":
        return "font-file", st
    if t == "/StructElem":
        return "struct-elem", ""
    if t == "/StructTreeRoot":
        return "struct-tree-root", ""
    if t == "/Page":
        return "page-dict", ""
    if t == "/Pages":
        return "pages-node", ""
    if t == "/XRef":
        return "xref-stream", ""
    if t == "/ObjStm":
        return "object-stream", ""
    if t == "/Metadata":
        return "metadata-xmp", ""
    if t == "/OCG" or t == "/OCMD":
        return "optional-content", ""
    if t == "/ExtGState":
        return "extgstate", ""
    if t == "/Annot":
        return "annotation", st
    if "/ICCBased" in str(obj.get("/Type", "")) :
        return "icc-profile", ""
    # streams with no /Type: content streams, ICC profiles, CMaps, ToUnicode
    if isinstance(obj, pikepdf.Stream):
        if "/N" in obj:                     # ICCBased profile stream
            return "icc-profile", "N=%s" % obj.get("/N")
        return "stream-untyped", filters_of(obj)
    return "other-dict", t or "(none)"


def analyze(path):
    pdf = pikepdf.open(path)
    total_objs = len(pdf.objects)
    stats = collections.defaultdict(lambda: [0, 0])   # cat -> [count, bytes]
    detail = collections.defaultdict(lambda: [0, 0])

    for i in range(total_objs):
        try:
            obj = pdf.objects[i]
        except Exception:
            continue
        cat, det = categorize(obj)
        n = raw_len(obj)
        stats[cat][0] += 1
        stats[cat][1] += n
        if det:
            detail[(cat, det)][0] += 1
            detail[(cat, det)][1] += n

    import os
    fsize = os.path.getsize(path)
    print("=" * 78)
    print("FILE  : %s" % os.path.basename(path))
    print("SIZE  : %s bytes (%.1f MB)" % (f"{fsize:,}", fsize / 1048576))
    print("PAGES : %d   OBJECTS: %s   PDF ver: %s"
          % (len(pdf.pages), f"{total_objs:,}", pdf.pdf_version))
    print("=" * 78)
    print("%-22s %9s %14s %8s" % ("CATEGORY", "COUNT", "BYTES", "% FILE"))
    print("-" * 78)
    acc = 0
    for cat, (c, b) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
        acc += b
        print("%-22s %9s %14s %7.1f%%" % (cat, f"{c:,}", f"{b:,}", 100 * b / fsize))
    print("-" * 78)
    print("%-22s %9s %14s %7.1f%%" % ("ACCOUNTED", "", f"{acc:,}", 100 * acc / fsize))
    print("%-22s %9s %14s %7.1f%%" % ("OVERHEAD (xref/etc)", "", f"{fsize-acc:,}",
                                      100 * (fsize - acc) / fsize))
    print()
    print("-- breakdown by detail (top 15) --")
    for (cat, det), (c, b) in sorted(detail.items(), key=lambda kv: -kv[1][1])[:15]:
        print("  %-20s %-22s %7s objs %14s" % (cat, det, f"{c:,}", f"{b:,}"))
    print()
    return stats


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyze(p)
