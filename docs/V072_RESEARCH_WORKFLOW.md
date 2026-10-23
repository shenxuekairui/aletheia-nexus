# 0.7.2 科研与 AI4S 工作流程

这一版完成“已有文献 → 找到证据 → 核对原页 → 带条件交给 AI”的本地流程。
原 PDF 始终保留。AN 提供可回查的材料，不自动给实验结果下结论。

## 1. 放入正文与补充材料

已有可信获取记录的文件直接使用，不必重新登记。没有记录的本地文件按题名登记：

```console
aletheia-nexus import paper.pdf --title "论文题名" --output-dir corpus
aletheia-nexus import supplement.pdf --title "补充材料题名" --role SUPPLEMENT --parent corpus/paper.pdf --output-dir corpus
aletheia-nexus library corpus
```

有真实 DOI 时可以为正文加 `--doi`；没有就留空。SI 通过父文档携带引用，不复用正文 DOI 冒充正文。
本地登记记为 `REGISTERED / DECLARED`，下游显示 `local_declared`；原获取验证仍是 `VERIFIED / MATCH`。
登记只复制文件、确认 PDF 可读并记录研究者提供的题录，不宣称题录经过自动核验。
相同文件名对应不同文件或身份时会报冲突，换一个输出目录即可。

## 2. 批量解析与继续运行

```console
aletheia-nexus parse-batch corpus
aletheia-nexus parse-batch corpus --retry-partial
```

每份 PDF 旁保存 `.parsed.json`；`parse-report.json` 逐篇更新 `COMPLETED / PARTIAL / FAILED / PENDING`。
中断后重复原命令。只有 PDF、身份记录、解析版本、配置和后端一致的现有结果才复用。
默认复用已有 partial；希望再试时加 `--retry-partial`。修改配置会重新解析。
单篇可用 `parse corpus/paper.pdf`；已有结果需显式 `--overwrite`。
批量有 partial 或 failed 时退出码为 6，已完成文件仍保留。

需要 OCR 时安装 Python 的 `ocr` extra，以及 Poppler、Tesseract 和所需语言包：

```console
aletheia-nexus parse-batch corpus --ocr --ocr-languages chi_sim+eng
```

工具不在 PATH 时使用 `--tesseract-command PATH` / `--renderer-command PATH`。
乱码、缺字、疑似符号编码错误、扫描页会显示不完整状态；OCR 不成功也会留下原因。
对文字充足且非整页图像的 PDF，OCR 主要补充空白区域和不确定文字；完整覆盖的干净原生文字不再因整页 OCR 的误读而产生大量重复复核项。需要比较的位置发生冲突时，保留两种读法并标明 `ocr-alternative`。数字、负号、单位、参比电极须回原页核对。
如果原生隐藏文字层明显乱码，而对应位置的 OCR 足够可靠，会优先展示 OCR，并把原始读法单独保留为 `native-alternative`；两者仍标记为需要复核。涉及数值的读法在符号、单位、大小写或百分号上存在差异时，不因整句话相似而合并。

短小、低置信度的数值／百分比行会进行有限的局部放大重读；最多每页每模型 3 行，改善明显才采用，并保留改变前的文字和不确定标记，无须新增参数。需要旋转／倾斜校正的页面暂不做这一步。原生乱码保留的可读文字及缺字数量也可辅助选择更完整的 OCR 主读法；相同位置、相同文字的替代候选合并模型来源。置信度高或多个模型一致，均不代表科学数值一定正确。
部分无 Unicode 映射的 Type 1 自定义字体可从嵌入字形恢复明确的负号和约等号。恢复项保留不确定标记，不按化学常识猜测缺失单位。
同一位置的中文单字若由原生文字与另一 OCR 模型共同支持、左右各两个汉字一致且没有相反读法，会进行校正并记录前后文本和依据；数字、单位及符号不参与该规则。校正行仍保留不确定提示。
`PARSED` 仅表示所配置的提取流程完成，不表示论文或数值已经获得科学认证。

需要更高质量的 OCR 时，可以指定已下载到本地的语言模型目录和分辨率；单篇 `parse` 与批量 `parse-batch` 均支持：

```console
aletheia-nexus parse-batch corpus --ocr --ocr-languages chi_sim+eng --ocr-tessdata-dir PATH_TO_TESSDATA_BEST --ocr-dpi 300
```

官方 `tessdata_best` 模型以更多耗时换取平均识别质量，但具体页面可能退步。本次真实扫描件中，它恢复了 `80%以上`，同时把原先能读出的 `92%以上` 识别坏了。需要保留第二种模型读法时使用：

```console
aletheia-nexus parse-batch corpus --ocr --ocr-languages chi_sim+eng --ocr-tessdata-dir PATH_TO_TESSDATA_BEST --ocr-alternative-tessdata-dir PATH_TO_EXISTING_TESSDATA --ocr-dpi 300
```

默认仍只用一个模型。双模型会增加耗时、输出量及冲突候选，不自动裁决哪份数值正确；正确文字可能只在替代读法中。中文需要 `chi_sim.traineddata`，英文需要 `eng.traineddata`，方向检测另需 `osd.traineddata`。模型由用户本地安装，AN 不在解析过程中下载。模型文件哈希随执行身份保存，行级来源区分模型；更换模型后不会静默复用旧解析结果。增加 DPI 并不保证改善，扫描原始像素不足时尤其如此。

## 3. 跨文献查找证据

```console
aletheia-nexus search corpus "乙醇酸 法拉第效率" --output results.json
aletheia-nexus search corpus "glycine nitrate" --mode or
aletheia-nexus search corpus "Faradaic efficiency" --exact
aletheia-nexus search corpus "400 33" --role SUPPLEMENT
```

默认 AND 要求词项同时出现在同一段落或可识别的表格内容单元内；OR 必须显式指定。
`--exact` 将整个查询作为短语；查询中的英文双引号也可圈定一个短语。
中文连续字符串可以匹配提取器在汉字之间插入的空格。检索视图统一全角、大小写、空格、常见横线、百分号前空格及数字间的居中小数点，规范原文不改变。
独立数字词项按完整书写数值匹配：`88.4` 不会命中 `188.4`，`5` 不会命中 `0.15`，也不会把科学计数法的指数当成独立数值。不带符号时按幅值查找，因此 `1.4` 可找到 `−1.4`；输入 `-1.4` 或 `+1.4` 时必须匹配相应符号。结果始终保留原文符号。检索不推断数值等价，`1.4` 与 `1.40` 不互相替代；带单位的引号短语仍按文字短语匹配。
英文不做词干推断，也不提供语义搜索。结果按短语匹配、词项覆盖和文本密度作固定排序；同分按文档身份和页码稳定排序。
当原生／主读法已经命中同一查询和同一空间位置时，该位置的重复替代读法排在其他证据之后，避免短 OCR 行挤占结果。替代读法仍保留；只有替代读法命中的恢复内容正常参与排序。此规则不判定科学数值的正误。

每条结果包含编号、稳定 ID、题名、正文／SI、PDF 实际页、原文片段、位置和不确定状态。
同一 PDF 的字节副本只检索一次；同 DOI 的不同 PDF 版本保留。当前使用每个 PDF 最新的有效解析版本。
文库会核对文件及身份记录；未解析、已改变、缺失或失败的文档列入未检索清单。
角色或章节筛选后，结果另列实际检索文档数、内容单元数及被筛选排除的文档，避免把整库可用数量当成本次检索范围。v3 工件的题名、文献 ID 和身份来源也须与来源记录一致。
没有命中只表示已检索内容没有匹配，不能代替覆盖不足部分的检查。

## 4. 回到原页

```console
aletheia-nexus open-source corpus results.json 1
aletheia-nexus open-source corpus results.json 1 --launch
```

输出本地 PDF 路径和从 1 开始的 PDF 实际页；SI 从自己的第 1 页计数。
`--launch` 打开系统阅读器。阅读器不支持跳页时，按输出的页码跳转。
PDF 实际页与印刷页码不一定相同，不自动把其中一个当成另一个。

## 5. 选择证据，补上条件页，再导出

```console
aletheia-nexus export corpus --results results.json --select 1,3 --preview
aletheia-nexus export corpus --results results.json --select 1,3 --context-page 1=4 --format markdown --output selected.md
aletheia-nexus export corpus --results results.json --select 1,3 --format json --output selected.json
aletheia-nexus export corpus --format jsonl --output corpus.jsonl
```

编号只对保存的 `results.json` 有意义，也可传稳定 ID。解析或来源变化后，旧结果选择会报过期，重新检索即可。
选择导出默认包含命中页前后各 1 页；`--context-pages 0` 仅取命中页；`--context-page 编号=页码` 补充远处的方法、条件或参比电极说明。
这只是页面范围展开，不声称自动识别了全部实验条件。
未提供 `--results` 时导出整个已解析文库。单篇旧的 Markdown、JSONL、chunks 接口继续可用。

`--preview` 展示范围、字符数、粗略 token 数和实际序列化字节数。
可加 `--budget-chars` 限制正文文本字符数：同一文档选中的页面上下文一起保留或明确跳过，不在数值中间截断。
token 估算按字符数 / 3，不能用于精确计费或保证模型窗口容量；来源清单的额外字节单独显示。
每份导出写明已纳入、跳过、部分解析、未检索文件，并保留角色、父文档、哈希及每段页码／位置。
跳过清单区分“未选择”和“预算不足”，与已纳入清单共同覆盖全部可用文档。表格块保留原文，并显式标记行列尚未解释、上下文是否完整及缺少的块；不会把表格文本直接认证为实验数据。图像元数据保留原页和对象位置，标记图内文字尚未验证，尤其需要核对坐标轴中的单位、参比电极和图例。该提示针对已识别图对象，不保证发现了全文所有图。
JSON 中 `source_uncertain` 保留规范工件的原始标记；导出的 `uncertain` 还包括表格解释的不确定性。规范工件和原文内容均不因此改写。
Markdown 来源可点击打开本地 PDF；分享时同时保留相对位置对应的文库。
证据包中的 `review_locations` 按原文位置组织块 ID，全部块各保留一次；同位置替代读法和同一图中的零散文字在 Markdown 中可展开查看。分组不裁决读法差异，不消除不确定性，也不将不同位置的原文矛盾合为一个值。图轴文字集中展示时仍须回原图解释，不能当作实验结果。

同一表格按 PDF 页集中为复核组，表头、单元格、注释和候选读法均保留；组数减少不代表消除了识别不确定性。JSON 同时提供观测到的行列位置，不代表已核验的实验数据。调用者可显式接入 [可选证据判断接口](V07_PARSING_CONTRACT.md#optional-reading-assessment)，默认解析不调用 AI。

导出直接复用解析结果，无需重新处理 PDF；相同内容重复导出会复用已有文件。
写入是原子的，中断后重跑即可。替换不同的现有派生文件需 `--overwrite`，不能覆盖原 PDF 或规范解析工件。
整个过程在本地运行，不自动上传论文或调用模型。

当前工作流与发布判定见 [整体验收](V072_RELEASE_ACCEPTANCE.md)；最新独立准确率及漏报见 [第三批独立验证](V072_THIRD_HOLDOUT.md)。当前仍有 3 处、5 项关键解析漏报，不能仅凭没有不确定标记直接使用科研数值。历史结果保留在 [内容解析专项复核](V072_PARSING_ACCURACY.md)和 [量化复核](V072_QUANTITATIVE_REVIEW.md)。

## 0.7.3 收尾范围

0.7.2 已承接本地／无 DOI／SI、检索、原文回查、批量恢复和两类导出，不将这些基础功能后移。
0.7.3 只修复实际使用暴露的版式、OCR、数值保真、速度、平台兼容和安装文档问题，并补上对应回归用例。
继续用同一批冻结 T0 及新增真实失败样本验收；保持 v2 可读和 v3 的来源约定。
0.7.3 完成后结束 0.7 系列，不增加向量库、知识图谱、科研语义抽取、自动结论、GUI 或通用 Agent 平台。
