# 案例：ABBYY OCR 后体积膨胀 4.4 倍

> 源文件是一本 608 页的中文扫描书。按仓库约定，标识信息（书名、文件名里的
> 馆藏号、正文与目录条目）一律隐去，只保留测量数据和方法。

| | 文件 | 大小 |
|---|---|---|
| 原始 | `original.pdf` | 26,730,205 B (25.49 MB) |
| ABBYY OCR 后 | `ocr.pdf` | 117,869,480 B (112.41 MB) |
| **增量** | | **+91,139,275 B (+4.41×)** |

608 页，430×652 pt，300 dpi 扫描书。

## 一、原始文件：几乎没有优化空间

```
PAGES : 608   OBJECTS: 1,963   PDF ver: 1.5
CATEGORY                   COUNT          BYTES   % FILE
image                        608     26,345,966    98.6%
  /CCITTFaxDecode            606      26,018,433
  /DCTDecode                   2         327,533     ← 彩色封面/封底
stream-untyped               608          27,232     0.1%   ← 页面内容流
OVERHEAD (xref/etc)                      357,007     1.3%
```

98.6% 是图像数据，非图像开销仅 0.36 MB。这是一个已经很干净的文件：606 页
`/ImageMask` + CCITT G4 (K=−1)，2 页彩色 JPEG。

## 二、字节归属核算（核算闭合，误差为 0）

```
python tools/pdf_page_diff.py original.pdf ocr.pdf
```

| 转换 | 页数 | 原 | 变后 | 增量 |
|---|---|---|---|---|
| CCITT G4 1-bit → **8-bit 灰度 JPEG** | 137 | 6,971,968 | **66,624,827** | **+59,652,859** |
| CCITT G4 → JBIG2（正常，有收益） | 469 | 19,046,465 | 13,502,009 | −5,544,456 |
| 彩色 JPEG → JPEG + ICC | 2 | 327,533 | 390,003 | +62,470 |
| **图像小计** | 608 | 26,345,966 | 80,516,839 | **+54,170,873** |
| **非图像**（标签树等） | | 384,239 | 37,352,641 | **+36,968,402** |
| **合计** | | | | **+91,139,275** ✓ |

`54,170,873 + 36,968,402 = 91,139,275`，与文件大小差值完全吻合。

### 冗余源 A：137 页被从 1-bit 提升到 8-bit 灰度 JPEG（+59.7 MB，占膨胀 65%）

ABBYY 把 137 页判定为「需要保留灰度」，重编码为灰度 JPEG。像素分析证明这是纯冗余：

```
page   14  ocr_jpeg= 513,404 B  mode=L  distinct_levels=212  %pixels_in_[0-15]+[240-255]=94.80%
           original CCITT for same page = 55,401 B  (ratio 9.3x)
page   15  ocr_jpeg= 455,337 B  mode=L  distinct_levels=203  %pixels_in_[0-15]+[240-255]=95.52%
           original CCITT for same page = 47,294 B  (ratio 9.6x)
```

- **94.8%–95.5% 的像素是纯黑或纯白**，却存在 200 多个灰阶
- 那些中间灰阶集中在笔画边缘 = **JPEG 振铃/模糊伪影**
- 源头是 1-bit 黑白扫描，8-bit 容器**携带的额外信息量为零**
- 代价：每页 9.3–9.7 倍

**136/137 页的图像尺寸与原始完全一致（1792×2681）**，只有第 607 页略有不同
（1760×2657 → 1762×2660）。尺寸一致意味着可以做像素级精确的原始流移植。

### 冗余源 B：281,242 个 StructElem 标签树（+37.0 MB，占膨胀 41%）

```
objects: 289,638   pages: 608
MarkInfo: {"/Marked": True}     has StructTreeRoot: True     Lang: zh-CN

抽样 966/289,638 个对象（每 300 个取 1）：
  /StructElem            938   97.10%   ~281,242 objs
  STREAM:/XObject         14    1.45%     ~4,197 objs
  /Page                    1    0.10%       ~299 objs
```

608 页产生了 **28.1 万个** `/StructElem`——平均每页 462 个，即每个文本行甚至
每个词一个标签。这是 PDF/UA 无障碍结构树。

**关键区分**：结构树 ≠ 可搜索文字。OCR 文字位于页面内容流中
（`BT /F0 9.97 Tf 3 Tr ... Tj ET`，`3 Tr` 即不可见渲染模式）。
删掉结构树，**搜索、复制、选中全部照常工作**，失去的只是屏幕阅读器语义和
重排（reflow）能力。

### 非冗余部分：OCR 文字层本身其实很小

17 个子集嵌入字体（SimSun / SimHei / TimesNewRoman / Arial 等，全部 CID
TrueType Identity-H），加上 608 个内容流，总共只有几百 KB。

**用户的直觉是对的：增加一个 OCR 图层不可能增加这么多体积。**
文字层不是元凶，图像重编码和标签树才是。

## 三、修复与结果

```bash
python tools/pdf_optimize.py ocr.pdf out.pdf --source original.pdf --strip-tags
```

策略：**把原始的 CCITT G4 流原样移植回 OCR 文件**。因为图像尺寸完全一致，
且只替换 `/Im0` 的像素载荷、不动几何与对象引用，所以不可见文字层的对齐关系
完全保持。

| 变体 | 处理 | 大小 | 相对 OCR |
|---|---|---|---|
| — | ABBYY 原始输出 | 112.41 MB | — |
| **C** | 仅重新打包对象流（不动图像） | 86.42 MB | −23.1% |
| **A** | 移植图像 + 重压缩，**保留标签树** | 29.53 MB | −73.7% |
| **B** | 移植图像 + 重压缩 + **剥离标签树** | 25.34 MB | −77.5% |
| **D** | B + 移植页改存 **JBIG2 通用模式** | 23.69 MB | −78.9% |
| **E** | D + **移植原始书签** ← 交付版 | **23.87 MB** | **−78.8%** |

各项贡献分离（可加）：

| 措施 | 节省 |
|---|---|
| 重新打包对象流（ABBYY 的对象流压缩得很差） | 25.99 MB |
| 图像去冗余（136 页移植 + 1 页重新二值化） | 56.89 MB |
| 剥离标签树 | 4.19 MB |
| **合计** | **87.07 MB** |

> 变体 B（25.34 MB）**比原始文件 25.49 MB 还小**，却带有完整的可搜索 OCR 文字层。

## 四、验证

```
python tools/pdf_verify.py ocr.pdf out_B.pdf
```

```
pages: 608 vs 608
geometry mismatches: 0
text: 679,401 chars (ref) vs 679,401 chars (cand); pages differing: 0
page 1/300/500/607/608 渲染差异 MAE = 0.000 ~ 2.656，无反色
```

**逐字节无损证明**——比对移植后与原始的 CCITT 流 SHA256：

```
pages where optimized CCITT stream == original CCITT stream (SHA256): 136
pages differing: 1 [607]      ← 尺寸不匹配，走 Otsu 重新二值化路径，属预期
```

**原生 300 dpi 墨量比对**（150 dpi 下的差异只是降采样抗锯齿假象）：

```
 page   ink_orig    ink_OPT  ink_ABBYY
   14     327504     327636     325545   opt-vs-orig +0.040%   abbyy-vs-orig -0.598%
  100     314744     314467     312912   opt-vs-orig -0.088%   abbyy-vs-orig -0.582%
  200     317067     315827     314305   opt-vs-orig -0.391%   abbyy-vs-orig -0.871%
```

优化版与原始的墨量差在 ±0.4% 以内，**且每一页都比 ABBYY 自己的输出更接近原始**。

## 五、JBIG2 追加优化（变体 D）

装上 jbig2enc 后（conda-forge 有 win-64 包，无需编译）对那 137 页再做压缩。
30 页抽样对照：

| 编码 | 30 页合计 | 相对 CCITT |
|---|---|---|
| CCITT G4（原始） | 1,330,533 B | — |
| JBIG2 通用模式 `-p` | 1,014,436 B | −23.8% |
| JBIG2 符号模式 `-s -p`（共享字典 67,132 B） | 865,248 B | −35.0% |

**符号模式虽小 11%，但不能用。** 它把视觉相似的字形聚类后共用一个符号，可能
把一个字替换成另一个字——这正是施乐扫描仪把数字调包的著名事故成因。对一本
含大量生僻字和特殊符号的学术专著，风险不可接受。jbig2enc 的无损变体 `-r` 又已
损坏：

```
Refinement broke in recent releases since it's rarely used.
If you need it you should bug agl@imperialviolet.org to fix it
```

所以采用**通用模式**（对原始位图做上下文算术编码，构造上无损）。实测每页
55,401 → 41,249 B（−26%），全书 25.34 MB → 23.69 MB。

**无损性验证**——解码后与原始 CCITT 逐像素比对：

```
grafted pages now stored as JBIG2: 137
  page   ink_orig    ink_opt  px_differing  verdict
    14     327504     327504             0  LOSSLESS
    15     292210     292210             0  LOSSLESS
    16     312635     312635             0  LOSSLESS
    ...
   606     313325     313325             0  LOSSLESS
   607  SHAPE MISMATCH (2657, 1760) vs (2660, 1762)   ← 重新二值化页，预期
```

### 那 469 页保留 ABBYY 的 JBIG2

我的通用模式对这 469 页只能压到 ~14.4 MB，而 ABBYY 的是 13.5 MB——它更小，
说明 ABBYY 用了符号模式。那它有损吗？逐像素查：

```
 page   ink_orig  ink_abbyy px_differing        %diff  verdict
    3      94598      94843        35329      0.7354%  DIFFERS
  150     284997     285508       125593      2.6142%  DIFFERS
  300     237831     237976       113561      2.3637%  DIFFERS
  500     232243     232397       107082      2.2289%  DIFFERS
```

约 2.3% 像素不同。进一步定性：

```
page 150   ink orig=284997 abbyy=285508
  no shift              :   125593 differing
  best shift dy=-1 dx=+0 :   114713 differing  (91.3% of the no-shift diff)
  abbyy ink outside 1px-dilated original: 4847 px
  original ink outside 1px-dilated abbyy: 4718 px
  connected components  : orig=1980 abbyy=1980 (+0.00%)
```

- **连通分量数完全相同**（1980/1980、1782/1782）→ 没有字形被增删
- 最佳位移只消掉 2–9% 的差异 → 不是整体偏移
- 99.9% 的差异像素落在对方 1 像素膨胀范围内 → 只是笔画边缘抖动

结论：ABBYY 做的是**轻微重新二值化/边缘平滑**，字符身份完全保留，不是符号
替换。属于「视觉等价但非逐字节相同」。因为它更小且无实质风险，予以保留。

> 注意：连通分量数**抓不到符号替换**——把「日」换成「曰」不改变分量数。这个
> 判据只能证明没有字形增删，不能证明没有替换。这也是不用符号模式的理由。

## 六、书签移植（变体 E）

ABBYY **把原始文件的 135 条书签全丢了**（三级层次，第 13–604 页）：

```
ORIGINAL   outline entries: 135
ABBYY_OCR  outline entries: 0
OPT        outline entries: 0
```

移植时踩到一个静默失败：原始书签用的是**命名目的地**
（`{'kind': 4, 'page': '13', 'view': 'Fit'}`），跨文档无法解析，
PyMuPDF 的 `set_toc` 会把它退化成 `{'kind': 0, 'page': -1}`——
**书签条目看着都在，点了哪儿也不去**。只数条数的检查完全通不过报警。

修正：把每条重建为本文档内的显式页面目标，并校验页码：

```
destinations: 0 explicit kept, 135 rebuilt as page targets, 0 dropped
check   : all 135 bookmarks resolve to the intended page (levels 1..3, pages 13..604)
```

再用 OCR 文字层反查落点——每条书签的标题文字确实出现在它指向的那一页
（标题内容已隐去）：

```
   page  13 contains '<一级标题>' : True
   page  13 contains '<二级标题>' : True
   page  15 contains '<二级标题>' : True
```

## 七、交付

`optimized.pdf` — 25,027,105 B (23.87 MB)

| | 大小 | 文字层 | 书签 |
|---|---|---|---|
| 原始（无 OCR） | 25.49 MB | 无 | 135 |
| ABBYY OCR 输出 | 112.41 MB | 679,401 字符 | **0（丢失）** |
| **交付版** | **23.87 MB** | 679,401 字符 | **135** |

比 ABBYY 输出小 **78.8%**，比没有文字层的原始文件还小 **1.62 MB**，
且书签比 ABBYY 版完整。

## 八、结论与可迁移的经验

1. **膨胀 100% 来自冗余，OCR 文字层无辜。** 65% 是位深升级，41% 是标签树，
   JBIG2 反而省了 6%。
2. **保留原始文件极其有价值。** 有原始 1-bit 流可移植，就能做到逐字节无损；
   没有的话只能重新二值化，会引入阈值判断误差。
3. **ABBYY 侧的预防措施**：导出时把图像压缩显式设为「黑白 / JBIG2」而非
   「自动」或「灰度」；不需要无障碍就关掉 PDF/UA 标签。
4. **重存一遍就能省 23%**——很多 OCR 工具的对象流压缩质量很差，这是零风险的
   免费收益。
5. **验证不能只看结构**。CCITT 的 `BlackIs1` 弄反会得到全页反色，而页数、
   几何、文字层检查全部通过。必须渲染像素。
6. **注意参照物是谁。** 把清晰的 1-bit 结果去比 ABBYY 那张模糊的灰度 JPEG，
   边缘必然差 5%，而且**我们的更忠实**。这类页要改用真正的源文件逐像素比对。
7. **JBIG2 只用通用模式。** 符号模式再小 11% 但有损，会替换相似字形。
8. **OCR 会丢书签，而且丢得很安静。** 移植时命名目的地跨文档失效，`set_toc`
   静默产出 page −1 的死书签。验证必须核对**页码**，不能只数条数。
