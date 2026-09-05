#!/usr/bin/env python
"""Remove redundancy from an OCR'd scan PDF without touching the text layer.

Three independent reductions, each opt-in:

  --graft-images  For pages an OCR engine re-encoded from 1-bit to 8-bit
                  grayscale/colour JPEG, put the ORIGINAL bilevel stream back.
                  Requires --source (the pre-OCR PDF). Lossless w.r.t. the
                  original scan and pixel-exact, so the invisible text layer
                  stays aligned: only the image payload is swapped, geometry
                  and object identity are untouched.

  --rebilevel     Same goal without a source PDF: threshold the grayscale page
                  back to 1-bit and re-encode as CCITT G4. Used as the fallback
                  when dimensions don't match, or standalone.

  --strip-tags    Drop the PDF/UA logical structure tree (/StructTreeRoot,
                  /MarkInfo, /StructParents). This does NOT affect searchable
                  text -- the text lives in page content streams. It only
                  removes reflow/screen-reader semantics.
"""
import argparse
import io
import os
import shutil
import subprocess
import tempfile

import pikepdf


def _find_jbig2():
    """Locate jbig2enc: $JBIG2_BIN, then PATH, then a conda env named pdfopt."""
    env = os.environ.get("JBIG2_BIN")
    if env and os.path.exists(env):
        return env
    found = shutil.which("jbig2")
    if found:
        return found
    prefix = os.environ.get("CONDA_PREFIX") or os.path.expanduser("~/anaconda3")
    for cand in (os.path.join(os.path.dirname(os.path.dirname(prefix)),
                              "envs", "pdfopt", "Library", "bin", "jbig2.exe"),
                 os.path.join(prefix, "envs", "pdfopt", "Library", "bin", "jbig2.exe"),
                 os.path.join(prefix, "envs", "pdfopt", "bin", "jbig2")):
        if os.path.exists(cand):
            return cand
    return "jbig2"      # let the caller fail with a clear message


# Install with:  conda create -n pdfopt -c conda-forge jbig2enc -y
JBIG2_BIN = _find_jbig2()

try:
    import numpy as np
    from PIL import Image, TiffImagePlugin
    # PIL splits TIFF output into ~64 KB strips by default. G4 restarts its
    # coder on every strip, so a multi-strip result cannot be spliced into a
    # PDF as one CCITTFaxDecode stream -- force a single strip.
    TiffImagePlugin.STRIP_SIZE = 1 << 31
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


# ---------------------------------------------------------------- discovery

def page_images(pageobj, depth=0, seen=None):
    """Every image XObject reachable from a page, recursing into Form XObjects."""
    if seen is None:
        seen = set()
    if depth > 8:
        return
    res = pageobj.get("/Resources", None)
    if res is None:
        return
    xo = res.get("/XObject", None)
    if not xo:
        return
    for _name, x in xo.items():
        try:
            g = x.objgen
        except Exception:
            g = None
        if g and g in seen:
            continue
        if g:
            seen.add(g)
        try:
            st = str(x.get("/Subtype"))
        except Exception:
            continue
        if st == "/Image":
            yield x
        elif st == "/Form":
            yield from page_images(x, depth + 1, seen)


def filters_of(x):
    f = x.get("/Filter")
    if f is None:
        return ""
    if isinstance(f, pikepdf.Array):
        return "+".join(str(v) for v in f)
    return str(f)


def raw_size(x):
    try:
        return int(x.get("/Length"))
    except Exception:
        try:
            return len(x.read_raw_bytes())
        except Exception:
            return 0


def is_bilevel(x):
    try:
        return int(x.get("/BitsPerComponent", 1)) == 1
    except Exception:
        return False


# ---------------------------------------------------------------- encoding

def ccitt_g4_encode(bilevel_img):
    """1-bit PIL image -> (g4_bytes, columns, rows, photometric).

    PIL has no raw G4 encoder, so round-trip through an in-memory TIFF and
    lift the strip out. Refuse multi-strip output: G4 strips cannot be
    concatenated, since each one restarts the coder.
    """
    buf = io.BytesIO()
    bilevel_img.save(buf, format="TIFF", compression="group4")
    buf.seek(0)
    t = Image.open(buf)
    offsets = t.tag_v2.get(273)          # StripOffsets
    counts = t.tag_v2.get(279)           # StripByteCounts
    photometric = t.tag_v2.get(262, 0)   # 0 = WhiteIsZero, 1 = BlackIsZero
    if not offsets or len(offsets) != 1:
        raise ValueError("multi-strip G4 TIFF (%s strips), cannot splice"
                         % (len(offsets) if offsets else 0))
    raw = buf.getvalue()[offsets[0]:offsets[0] + counts[0]]
    return raw, t.size[0], t.size[1], int(photometric)


def set_ccitt(img, data, cols, rows, black_is_1=False):
    """Rewrite an image XObject in place as 1-bit DeviceGray CCITT G4."""
    parms = pikepdf.Dictionary(Columns=cols, Rows=rows, K=-1)
    if black_is_1:
        parms["/BlackIs1"] = True
    img.write(data, filter=pikepdf.Name("/CCITTFaxDecode"), decode_parms=parms)
    img["/ColorSpace"] = pikepdf.Name("/DeviceGray")
    img["/BitsPerComponent"] = 1
    img["/Width"] = cols
    img["/Height"] = rows
    for k in ("/SMask", "/Mask", "/ImageMask", "/Decode", "/Interpolate"):
        if k in img:
            del img[k]


def jbig2_generic_encode(bilevel_img, binary=JBIG2_BIN):
    """1-bit PIL image -> JBIG2 embedded-stream bytes, losslessly.

    Deliberately GENERIC region coding (no -s). jbig2enc's symbol mode is ~30%
    smaller but lossy: it clusters visually similar glyphs and can substitute
    one for another -- the failure that produced the well-known Xerox
    digit-swapping bug. Its lossless variant (-r, refinement) is broken
    upstream and refuses to run, so generic coding is the only safe option.
    """
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "page.png")
        bilevel_img.save(png)
        r = subprocess.run([binary, "-p", png], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            raise RuntimeError("jbig2 failed (rc=%s): %s"
                               % (r.returncode, r.stderr.decode("utf-8", "replace")[:200]))
        return r.stdout


def set_jbig2(img, data, cols, rows):
    """Rewrite an image XObject in place as a 1-bit JBIG2 generic region."""
    img.write(data, filter=pikepdf.Name("/JBIG2Decode"))
    img["/ColorSpace"] = pikepdf.Name("/DeviceGray")
    img["/BitsPerComponent"] = 1
    img["/Width"] = cols
    img["/Height"] = rows
    for k in ("/SMask", "/Mask", "/ImageMask", "/Decode", "/Interpolate", "/DecodeParms"):
        if k in img:
            del img[k]


def to_bilevel_pil(x):
    """Decode any image XObject pikepdf can read into a 1-bit PIL image."""
    im = pikepdf.PdfImage(x).as_pil_image()
    return im if im.mode == "1" else im.convert("L").point(lambda v: 255 if v > 127 else 0, "1")


def otsu_threshold(arr):
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1 - omega)
    denom[denom == 0] = 1e-12
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    return int(np.argmax(sigma_b))


# ---------------------------------------------------------------- main pass

def optimize(ocr_path, out_path, source_path=None, do_graft=True,
             do_rebilevel=True, do_strip_tags=False, do_jbig2=False,
             jbig2_bin=JBIG2_BIN, verbose=True):
    pdf = pikepdf.open(ocr_path, allow_overwriting_input=False)
    src = pikepdf.open(source_path) if source_path else None

    n_pages = len(pdf.pages)
    if src and len(src.pages) != n_pages:
        print("WARNING: source has %d pages, target has %d -- grafting disabled"
              % (len(src.pages), n_pages))
        src = None

    stats = {"grafted": 0, "grafted_saved": 0,
             "rebileveled": 0, "rebilevel_saved": 0,
             "skipped_ok": 0, "skipped_colour": 0, "failed": 0}

    for i in range(n_pages):
        tgt = list(page_images(pdf.pages[i].obj))
        if len(tgt) != 1:
            stats["skipped_colour"] += 1
            continue
        img = tgt[0]
        if is_bilevel(img):
            stats["skipped_ok"] += 1        # already 1-bit (JBIG2/CCITT) -- leave it
            continue

        before = raw_size(img)
        w, h = int(img.get("/Width")), int(img.get("/Height"))

        # 1) graft the original bilevel stream if it matches pixel-for-pixel
        if do_graft and src:
            s = list(page_images(src.pages[i].obj))
            if len(s) == 1 and is_bilevel(s[0]) \
               and int(s[0].get("/Width")) == w and int(s[0].get("/Height")) == h \
               and "CCITT" in filters_of(s[0]):
                dp = s[0].get("/DecodeParms") or {}
                if isinstance(dp, pikepdf.Array):
                    dp = dp[0] if len(dp) and dp[0] is not None else {}
                try:
                    if do_jbig2:
                        # Same pixels, denser codec. Decoding the source CCITT
                        # and re-coding as JBIG2 generic stays lossless.
                        data = jbig2_generic_encode(to_bilevel_pil(s[0]), jbig2_bin)
                        set_jbig2(img, data, w, h)
                    else:
                        set_ccitt(img, s[0].read_raw_bytes(), w, h,
                                  black_is_1=bool(dp.get("/BlackIs1", False)))
                    stats["grafted"] += 1
                    stats["grafted_saved"] += before - raw_size(img)
                    if verbose and stats["grafted"] <= 3:
                        print("  page %4d grafted: %s -> %s bytes"
                              % (i + 1, f"{before:,}", f"{raw_size(img):,}"))
                    continue
                except Exception as e:
                    print("  page %d graft failed: %s" % (i + 1, e))

        # 2) fall back to re-thresholding the raster ourselves
        if do_rebilevel and HAVE_PIL:
            try:
                pim = pikepdf.PdfImage(img).as_pil_image()
                g = pim if pim.mode in ("L", "1") else pim.convert("L")
                arr = np.asarray(g.convert("L"))
                thr = otsu_threshold(arr)
                bw = Image.fromarray((arr > thr).astype(np.uint8) * 255).convert("1")
                if do_jbig2:
                    set_jbig2(img, jbig2_generic_encode(bw, jbig2_bin), bw.size[0], bw.size[1])
                else:
                    data, cols, rows, photometric = ccitt_g4_encode(bw)
                    # CCITT default (BlackIs1 false) means 0 bits are black,
                    # which matches TIFF photometric 0 (WhiteIsZero).
                    set_ccitt(img, data, cols, rows, black_is_1=(photometric == 1))
                stats["rebileveled"] += 1
                stats["rebilevel_saved"] += before - raw_size(img)
                if verbose and stats["rebileveled"] <= 3:
                    print("  page %4d rebileveled (thr=%d): %s -> %s bytes"
                          % (i + 1, thr, f"{before:,}", f"{raw_size(img):,}"))
                continue
            except Exception as e:
                print("  page %d rebilevel failed: %s" % (i + 1, e))
                stats["failed"] += 1
                continue

        stats["failed"] += 1

    # 3) structure tree
    if do_strip_tags:
        removed = 0
        root = pdf.Root
        for k in ("/StructTreeRoot", "/MarkInfo"):
            if k in root:
                del root[k]
                removed += 1
        for p in pdf.pages:
            if "/StructParents" in p.obj:
                del p.obj["/StructParents"]
        print("  stripped structure tree (%d catalog keys + /StructParents)" % removed)

    pdf.remove_unreferenced_resources()
    pdf.save(out_path,
             object_stream_mode=pikepdf.ObjectStreamMode.generate,
             compress_streams=True,
             recompress_flate=True,
             linearize=False)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ocr_pdf")
    ap.add_argument("out_pdf")
    ap.add_argument("--source", help="pre-OCR original PDF to graft bilevel images from")
    ap.add_argument("--no-graft", action="store_true")
    ap.add_argument("--no-rebilevel", action="store_true")
    ap.add_argument("--strip-tags", action="store_true",
                    help="remove the logical structure tree (keeps searchable text)")
    ap.add_argument("--jbig2", action="store_true",
                    help="encode rewritten pages as JBIG2 generic region instead of "
                         "CCITT G4 (lossless, ~25%% smaller); needs jbig2enc")
    ap.add_argument("--jbig2-bin", default=JBIG2_BIN, help="path to jbig2.exe")
    a = ap.parse_args()

    if a.jbig2 and not (os.path.exists(a.jbig2_bin) or shutil.which(a.jbig2_bin)):
        ap.error("jbig2 binary not found (%s). Install it with:  "
                 "conda create -n pdfopt -c conda-forge jbig2enc -y   "
                 "or point --jbig2-bin / $JBIG2_BIN at it." % a.jbig2_bin)

    b0 = os.path.getsize(a.ocr_pdf)
    print("input : %s  (%.2f MB)" % (os.path.basename(a.ocr_pdf), b0 / 1048576))
    st = optimize(a.ocr_pdf, a.out_pdf, a.source,
                  do_graft=not a.no_graft,
                  do_rebilevel=not a.no_rebilevel,
                  do_strip_tags=a.strip_tags,
                  do_jbig2=a.jbig2,
                  jbig2_bin=a.jbig2_bin)
    b1 = os.path.getsize(a.out_pdf)
    print()
    print("pages grafted     : %4d  (image bytes saved %s)"
          % (st["grafted"], f"{st['grafted_saved']:,}"))
    print("pages rebileveled : %4d  (image bytes saved %s)"
          % (st["rebileveled"], f"{st['rebilevel_saved']:,}"))
    print("pages already 1bit: %4d" % st["skipped_ok"])
    print("pages left alone  : %4d  (colour / multi-image)" % st["skipped_colour"])
    print("failures          : %4d" % st["failed"])
    print()
    print("output: %s  (%.2f MB)" % (os.path.basename(a.out_pdf), b1 / 1048576))
    print("RESULT: %.2f MB -> %.2f MB   %.1f%% smaller   (%.2fx)"
          % (b0 / 1048576, b1 / 1048576, 100 * (1 - b1 / b0), b0 / b1))


if __name__ == "__main__":
    main()
