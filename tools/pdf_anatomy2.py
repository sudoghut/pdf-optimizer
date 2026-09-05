#!/usr/bin/env python
"""Accurate byte accounting for a PDF, including objects stored in object streams.

pdf_anatomy.py could not price non-stream objects (dictionaries), which is
exactly where a tagged-PDF structure tree lives. This version:
  * prices every stream from its /Length (raw, as-stored -- fast, no decode)
  * reports /ObjStm streams as one bucket: the compressed container holding
    all non-stream objects
  * counts non-stream objects by /Type so that bucket can be attributed
"""
import sys
import os
import collections
import pikepdf


def filters_of(d):
    try:
        f = d.get("/Filter")
    except Exception:
        return ""
    if f is None:
        return "(none)"
    if isinstance(f, pikepdf.Array):
        return "+".join(str(x) for x in f)
    return str(f)


def stream_category(obj):
    t = str(obj.get("/Type")) if "/Type" in obj else ""
    st = str(obj.get("/Subtype")) if "/Subtype" in obj else ""
    if st == "/Image":
        return "image-data", filters_of(obj)
    if st == "/Form":
        return "form-xobject", filters_of(obj)
    if t == "/ObjStm":
        return "OBJECT-STREAMS (compressed dicts)", ""
    if t == "/XRef":
        return "xref-stream", ""
    if t == "/Metadata":
        return "metadata-xmp", ""
    if t == "/EmbeddedFile":
        return "embedded-file", ""
    if st in ("/CIDFontType0C", "/Type1C", "/OpenType") or t in ("/Font",):
        return "font-file", st or t
    if "/N" in obj and "/Length" in obj and t == "" and st == "":
        # ICCBased profile streams carry /N (component count) and nothing else
        return "icc-profile", "N=%s" % obj.get("/N")
    return "stream-other", filters_of(obj)


def main(path):
    pdf = pikepdf.open(path)
    fsize = os.path.getsize(path)
    n = len(pdf.objects)

    streams = collections.defaultdict(lambda: [0, 0])
    detail = collections.defaultdict(lambda: [0, 0])
    dicts = collections.Counter()
    fontfile_bytes = 0
    fontfile_n = 0

    for i in range(n):
        try:
            obj = pdf.objects[i]
        except Exception:
            continue
        if isinstance(obj, pikepdf.Stream):
            try:
                ln = int(obj.get("/Length"))
            except Exception:
                try:
                    ln = len(obj.read_raw_bytes())
                except Exception:
                    ln = 0
            cat, det = stream_category(obj)
            streams[cat][0] += 1
            streams[cat][1] += ln
            if det:
                detail[(cat, det)][0] += 1
                detail[(cat, det)][1] += ln
        elif isinstance(obj, pikepdf.Dictionary):
            t = str(obj.get("/Type")) if "/Type" in obj else "(no /Type)"
            dicts[t] += 1
            # embedded font programs hang off FontDescriptor
            if t == "/FontDescriptor":
                for k in ("/FontFile", "/FontFile2", "/FontFile3"):
                    if k in obj:
                        try:
                            fontfile_bytes += int(obj[k].get("/Length"))
                            fontfile_n += 1
                        except Exception:
                            pass
        else:
            dicts["(non-dict: %s)" % type(obj).__name__] += 1

    print("=" * 80)
    print("FILE  : %s" % os.path.basename(path))
    print("SIZE  : %s bytes (%.2f MB)" % (f"{fsize:,}", fsize / 1048576))
    print("PAGES : %d   INDIRECT OBJECTS: %s" % (len(pdf.pages), f"{n:,}"))
    print("=" * 80)
    print("%-38s %8s %14s %8s" % ("STREAM CATEGORY", "COUNT", "BYTES", "% FILE"))
    print("-" * 80)
    acc = 0
    for cat, (c, b) in sorted(streams.items(), key=lambda kv: -kv[1][1]):
        acc += b
        print("%-38s %8s %14s %7.2f%%" % (cat, f"{c:,}", f"{b:,}", 100 * b / fsize))
    print("-" * 80)
    print("%-38s %8s %14s %7.2f%%" % ("all stream payloads", "", f"{acc:,}", 100 * acc / fsize))
    print("%-38s %8s %14s %7.2f%%" % ("everything else (xref,dict syntax)", "",
                                      f"{fsize-acc:,}", 100 * (fsize - acc) / fsize))
    print()
    print("embedded font programs: %d files, %s bytes" % (fontfile_n, f"{fontfile_bytes:,}"))
    print()
    print("-- stream detail (top 12) --")
    for (cat, det), (c, b) in sorted(detail.items(), key=lambda kv: -kv[1][1])[:12]:
        print("  %-36s %-16s %8s objs %14s" % (cat, det, f"{c:,}", f"{b:,}"))
    print()
    print("-- NON-STREAM objects by /Type (these live inside OBJECT-STREAMS) --")
    tot_d = sum(dicts.values())
    for t, c in dicts.most_common(15):
        print("  %-34s %10s  %5.1f%% of dicts" % (t, f"{c:,}", 100 * c / max(tot_d, 1)))
    print("  %-34s %10s" % ("TOTAL non-stream objects", f"{tot_d:,}"))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
        print()
