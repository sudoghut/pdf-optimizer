# pdf-optimizer

分析 PDF 的体积构成，定位**冗余**，并在不损失信息的前提下把它去掉。

前提假设：一个文件不会凭空获得信息。如果一份 PDF 经过某道处理后体积变大了，
增加的字节要么是真的新信息（罕见），要么是冗余（常见）。本仓库的方法就是把每
一个字节归位到具体对象，然后判定它属于哪一类。

## 方法论：四步

### 1. 先做字节归属核算，不要猜

绝大多数「PDF 太大」的讨论直接跳到「用某某工具压一下」。那是赌博。先回答
**字节到底在哪儿**，再决定动什么。

```bash
python tools/pdf_anatomy2.py file.pdf
```

按对象类别统计每个流的实际存储字节，并把非流对象（字典）按 `/Type` 计数——
标签树、注释这类东西压缩在对象流里，逐页工具根本看不见它们。

核算必须**闭合**：各项增量之和应当等于文件大小的差值。对不上就说明还有没找到
的东西。

### 2. 逐页对比编码参数

```bash
python tools/pdf_page_diff.py before.pdf after.pdf
```

按「编码 + 色彩空间 + 位深」给每页签名，然后按*转换类型*聚合，指出每一类转换
花了多少字节。这能一眼看出「1-bit CCITT → 8-bit 灰度 JPEG」这种典型灾难。

注意它会递归进 Form XObject——很多 OCR 引擎（ABBYY 就是）把页面图像包在
Form XObject 里，不递归的话你会一张图都找不到。

### 3. 判定「新增字节是否携带新信息」

这是核心判据。对被怀疑的图像做像素分析：

- 8-bit 灰度页里 95% 的像素是纯黑或纯白，剩下的是笔画边缘的中间灰阶
  → 那些灰阶是 **JPEG 振铃伪影**，源头是 1-bit，信息增量为零，纯冗余。
- 真彩色照片页的 8-bit 才是真信息，不能动。

### 4. 用最小改动去掉冗余，然后验证

```bash
python tools/pdf_optimize.py in.pdf out.pdf --source original.pdf --strip-tags
python tools/pdf_verify.py in.pdf out.pdf
```

验证必须查三样，缺一不可：页数/几何、**文字层逐页比对**、**渲染像素**。
只做结构检查会漏掉 CCITT 黑白反转（`BlackIs1` 弄反）和图像错位。

## 冗余的常见来源（按实战命中率排序）

| 来源 | 症状 | 处理 |
|---|---|---|
| **位深升级** | 1-bit 扫描页被重编码成 8-bit 灰度/RGB JPEG | 移植原始 1-bit 流；或重新二值化 |
| **对象流未压缩** | 对象数巨大但文件里字典没打包 | 用 `object_stream_mode=generate` 重存 |
| **标签树** | `/StructElem` 数量 ≫ 页数（每行甚至每词一个） | `--strip-tags`（**不影响可搜索文字**） |
| 重复资源 | 同一字体/图像嵌入多份 | 去重后指向同一对象 |
| 过度采样 | 600+ dpi 的纯文字页 | 降采样到 300 dpi |
| 缩略图 / `/PieceInfo` | 编辑器私有数据 | 直接删 |

### 关于位图编码的选择

对 1-bit 扫描文本页：**JBIG2 < CCITT G4 ≪ 灰度 JPEG**。

`jbig2enc` 从 conda-forge 装即可，Windows 有现成 win-64 包，**不必自己编译**：

```bash
conda create -n pdfopt -c conda-forge jbig2enc -y
```

`pdf_optimize.py` 会自动从 `$JBIG2_BIN`、`PATH`、名为 `pdfopt` 的 conda 环境里
找到它，也可以用 `--jbig2-bin` 直接指定。

**只用通用模式（`-p`，不加 `-s`）。** 符号模式再小约 11%，但它把视觉相似的
字形聚类共用一个符号，可能**把一个字替换成另一个字**——施乐扫描仪数字调包
事故就是这么来的。其无损变体 `-r` 在 jbig2enc 上游已损坏，运行会直接拒绝。
通用模式是对位图做上下文算术编码，构造上无损，实测每页比 CCITT G4 小 26%。

含图文混排的页面应考虑 MRC（分层：文字层二值化 + 图片层 JPEG），这是商业
OCR 产品「高压缩」模式的原理。

### 别忘了书签

OCR 引擎经常把大纲整个丢掉（本案例 135 条全没了）。移植时**必须重建目的地**：
命名目的地跨文档无法解析，`set_toc` 会静默退化成 page −1 的死书签。校验要核对
**页码**，不能只数条数。

## 工具

| 脚本 | 用途 |
|---|---|
| `tools/pdf_anatomy.py` | 快速分类统计（仅流对象，早期版本） |
| `tools/pdf_anatomy2.py` | 完整字节归属，含对象流内字典计数 |
| `tools/pdf_page_diff.py` | 两份 PDF 的逐页编码转换对比 |
| `tools/pdf_optimize.py` | 移植原始位图 / 重新二值化 / JBIG2 / 剥离标签树 / 重压缩 |
| `tools/pdf_verify.py` | 页数、几何、文字层、渲染像素四重验证 |
| `tools/pdf_bookmarks.py` | 查看 / 跨文件移植书签（重建目的地并校验页码） |

依赖：`pikepdf`、`Pillow`、`numpy`、`scipy`、`PyMuPDF`（验证用）、
`jbig2enc`（可选，见上）。

给 agent 的操作说明见 [`AGENTS.md`](AGENTS.md)；
逐案例工作流见 [`.claude/skills/pdf-case/SKILL.md`](.claude/skills/pdf-case/SKILL.md)
（在 Claude Code 里输入 `/pdf-case` 触发）。

## 案例

- [`cases/ocr-bitdepth-inflation/`](cases/ocr-bitdepth-inflation/) — 一本 608 页
  中文扫描书经 ABBYY OCR 后体积涨 4.4 倍（25.5 MB → 112.4 MB）。定位为两处冗余：
  137 页从 1-bit 提升到 8-bit 灰度 JPEG（+59.7 MB），以及 281,242 个 StructElem
  标签树（+37.0 MB）。修复后 **23.9 MB —— 比原始文件还小 1.6 MB，带完整 OCR
  文字层和移植回来的 135 条书签**（ABBYY 把书签全丢了）。

案例记录只保留测量数据和方法，不含源文件的标识信息。

## License

MIT — see [LICENSE](LICENSE).
