# 案例：1-bit 内容被存成 RGB JPEG 的扫描书（304 MB → 12 MB）

> 源文件是一本 419 页的中文扫描书，无 OCR 文字层，也没有更早的 1-bit 原始版本。
> 按仓库约定，标识信息一律隐去，只保留测量数据和方法。

| | 文件 | 大小 |
|---|---|---|
| 原始 | `original.pdf` | 319,303,915 B (304.51 MB) |
| 变体 A：CCITT G4 | `opt_ccitt.pdf` | 17,523,777 B (16.71 MB) |
| **变体 B：JBIG2 通用模式 ← 交付版** | `optimized.pdf` | **13,205,104 B (12.59 MB)** |

419 页，约 395.5×581 pt，图像 1666×2421（300 dpi）。

## 一、字节归属核算

```
PAGES : 419   INDIRECT OBJECTS: 1,351
image-data      419   319,076,472   99.93%     (全部 /DCTDecode)
stream-other    419        18,443    0.01%     (页面内容流)
everything else            209,000    0.07%
embedded font programs: 0
```

`319,076,472 + 18,443 + 209,000 = 319,303,915`，与文件大小一致。

每页一张整页 RGB JPEG（`DeviceRGB`，8 bit），每页 130–1,020 KB，中位数 778 KB。
没有字体、没有文字层、没有标签树，非图像开销只有 0.07%。**体积 100% 在页面图像里。**

## 二、冗余判定：像素证据

对全部 419 页解码后统计「中间灰阶」（灰度落在 16–239）占比和最大色差：

```
mid>0.01%:  [1, 2]
chroma>24:  [1, 2]
max mid among pages>=3: 0.00007 (%)
```

抽样页：

```
page   3  levels=26  extreme%=100.00
page  11  levels=32  extreme%=100.00
page 201  levels=32  extreme%=100.00
page 419  levels=27  extreme%=100.00
page   1  levels=195 extreme%=79.72   ← 彩色封面
page   2  levels=193 extreme%=94.24   ← 彩色封面
```

- 第 3–419 页：**所有像素都落在 [0,15] ∪ [240,255]**，RGB 三通道一致（色差 0），
  全部 417 页合计只有 **258 个** 中间灰阶像素。这是 1-bit 黑白内容被塞进 24 位
  JPEG 容器，信息增量为零 → **冗余，可去**。
- 第 1–2 页：彩色，中间灰阶占 20% / 5.6%，**真信息，不动**。

### 阈值陷阱

第一版工具对这些页用 Otsu 选阈值，得到 thr=12、14、17 ——落在深色簇 [0,15]
**内部**，会把一部分「JPEG 振铃级别的墨」判成白纸。因为这些页没有中间灰阶，
16–239 内任何阈值结果都相同，所以改为固定取 127，并在工具里加了护栏：
中间灰阶占比 >0.01% 或有色偏的页面一律保留不动。

## 三、变体对照

```bash
python tools/pdf_optimize.py original.pdf opt_ccitt.pdf
python tools/pdf_optimize.py original.pdf opt_jbig2.pdf --jbig2
```

```
CCITT : pages rebileveled 417 (image bytes saved 301,715,729)   RESULT 304.51 MB -> 16.71 MB (18.22x)
JBIG2 : pages rebileveled 417 (image bytes saved 306,005,974)   RESULT 304.51 MB -> 12.59 MB (24.18x)
pages left alone: 2 (colour)    failures: 0
```

| 变体 | 大小 | 相对原始 |
|---|---|---|
| 原始 | 304.51 MB | — |
| A：417 页 → 1-bit CCITT G4，2 页封面保留 | 16.71 MB | −94.5% |
| **B：417 页 → 1-bit JBIG2 通用模式** | **12.59 MB** | **−95.9%** |

JBIG2 只用通用模式（`-p`，不加 `-s`），没有符号替换风险。相对 CCITT G4 再小约 25%。

## 四、验证

```
python tools/pdf_verify.py original.pdf opt_jbig2.pdf --dpi 300
```

```
pages: 419 vs 419
geometry mismatches: 0
text: 0 chars (ref) vs 0 chars (cand); pages differing: 0

rendered comparison @ 300 dpi
  page   ref_mean  cand_mean       MAE   %pix>32  verdict
     1     242.25     242.25     0.000     0.00%  ok
    14     229.57     229.67     0.310     0.00%  ok
    15     229.38     229.47     0.304     0.00%  ok
    16     233.27     233.38     0.297     0.00%  ok
   100     240.27     240.34     0.193     0.00%  ok
   300     240.68     240.74     0.178     0.00%  ok

PASS
```

（`cand_mean` 略高于 `ref_mean` 是因为 JPEG 振铃级别的 13–15 灰度墨被收敛为纯黑/纯白。）

**逐像素证明**：用 MuPDF 解码优化后的 JBIG2，与「原始 JPEG 解码后按 127 二值化」比较：

```
pages compared 417  total differing px 0  pages differing []  | mid-grey px total 258
toc equal (level,page): True 90
```

417 页零像素差异，书签 90 条的层级与页码全部一致。

注意措辞：这是**相对于原始 JPEG 的二值化结果**逐像素相同，而不是相对于某个更早的
1-bit 扫描源——后者不存在。JPEG 的振铃级别灰阶（13–15 与 240–255）被折叠成纯黑
/纯白，这正是判定为冗余的那部分。

## 五、结论与可迁移经验

1. **RGB、8-bit 不等于彩色。** 先看直方图：417/419 页 100% 像素在两端，且 RGB 三
   通道一致，是 1-bit 内容的 JPEG 外壳，替换后 304 MB 降到 12.6 MB。
2. **没有 1-bit 源时可以重新二值化，但要先证明没有中间灰阶。** 这里中间灰阶总共
   258 个像素，所以阈值没有歧义；有真实灰度的页（这里是封面）必须原样保留。
3. **不要盲信 Otsu。** 双峰数据且两簇之间是空的时，Otsu 可能落在簇内部，改用簇
   间中点（127）。
4. **工具护栏**：`pdf_optimize.py` 现在对中间灰阶 >0.01% 或有色偏的页面自动跳过。
5. 文件本身没有文字层。若需要可搜索，应在二值化后的文件上再做 OCR；那是另一个
   步骤，不在本案例范围内。
6. 书签在 pikepdf 重写中原样保留（90 条，核对了页码）。

## 六、检索来源

- [Not All PDF Compression is Created Equal（Foxit）](https://www.foxit.com/landingpage/2020/not-all-pdf-compression-is-created-equal/)：JBIG2 对扫描文本比 G4 小；扫描噪点会降低字形匹配率。
- [Scan to PDF/A – some insights（pdf-tools）](https://www.pdf-tools.com/pdf-knowledge/how-scan-pdfa/)：无损 JBIG2 通常仍优于 G4；有损模式有替换字符风险；MRC 可把一页压到约 40 KB 但属于有损。
- [Mixed Raster Content（Leadtools）](https://www.leadtools.com/help/sdk/mapping/mixed-raster-content-mrc.html)：MRC 的蒙版 + 背景/前景分层原理（本案例无需，封面只有 2 页）。
- 检索「这个生产工具的已知膨胀原因」未找到针对该生成器的资料，结论只来自本文件的实测。
