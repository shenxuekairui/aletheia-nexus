# 论文清单规范化：本地接口

此接口让可信本机工具把粘贴文字整理成论文获取预览。它与界面共用输入解析和模型服务，
不会下载论文、改动浏览器里的获取草稿、创建分类目录或读取整个文库。
普通用户可以直接使用[工作台手册](WORKBENCH_USER_GUIDE.md#任意文本的手动与模型规范化)中的
“手动整理并预览”“AI 整理输入”“确认采用并预览”。

接口随现有 Local Web UI 启动，使用同一地址和端口。默认基址为：

```text
http://127.0.0.1:8080/an-api/input-normalization
```

## 本机访问凭证与权限

所有端点，包括手动解析和读取状态，都需要请求头 `X-AN-Preview-Token`。
从工作台中显式提供的本地接口入口取得当前进程的临时能力令牌；接口不提供公开的令牌读取端点，
也不接受查询参数中的令牌。重启服务会更换令牌，它不写入预设、任务参数或结果导出。

**这个令牌可以提交模型规范化任务，可能产生费用，并非只读凭证。**
只交给可信的本机工具；每个模型任务仍须明确提供本次授权与费用上限。
它不是 DeepSeek API 密钥，服务商密钥继续从原有环境变量读取，接口不接收或返回密钥。

服务只接受 `127.0.0.1` 或 `localhost` 的本地访问。浏览器请求必须同源；拒绝跨站访问，不开放 CORS。
本地脚本可不带 `Origin`，但仍必须提供有效令牌。若使用不同 UI 端口，相应替换下面示例地址。

## 请求边界

| 项目 | 规则 |
| --- | --- |
| 内容类型 | `application/json` |
| 完整请求体 | 最多 256 KiB |
| `text` | 非空字符串，最多 50000 字符且不超过 200000 个 UTF-8 字节；不含 NUL |
| 输入来源 | 只接受文字；不接受本地文件路径对象、任意 URL 抓取或 PDF 上传 |
| 未知字段 | 拒绝，不能把未支持参数或密钥夹带进请求 |
| 单次模型请求 | `max_calls` 固定为 1，模型自动重试次数固定为 0 |
| 模型输出上限 | `max_output_tokens` 为 128–8192；不是保证能处理任意篇数 |
| 费用 | 模型请求必须明确正有限数 `options.max_cost` 和 `options.model.currency`（`CNY` / `USD`） |

长清单应分批。原文在输入大小内，不代表模型输出一定能容纳全部条目；截断或验证失败时不得直接采用部分猜测。
费用按本次模型配置与实际返回用量记录，不预先承诺夜间折扣，也不把配置估算当作服务商最终账单。

## 手动整理：无模型调用

`POST /manual` 仅接收：

```json
{
  "text": "[电合成] | 标签=待读\n10.1234/example-01\n10.1234/example-02 | 分类=/ | 标签=[]"
}
```

这里的 DOI 仅为格式占位符，不代表真实论文。可改用自己的 DOI、标题、明确分类分组和行内设置。
该端点调用既有的本地输入解析，不根据论文内容自行分类，也不进行书目查询。

响应为 HTTP 200：

```json
{
  "mode": "manual",
  "preview": {
    "items": [],
    "errors": [],
    "warnings": [],
    "conflicts": [],
    "count": 0,
    "paper_count": 0,
    "ready": true
  },
  "downloads_started": false
}
```

上述空数组仅示意响应结构。实际响应包含逐篇结果；HTTP 200 不代表每篇都有效，
应同时检查 `preview.ready`、`errors` 和 `conflicts`。每项保留稳定编号、原行号、书目请求及分类/标签模式。
完全相同的重复输入会提示去重；同一 DOI 的不同分类、标签、命名或书目约束会列为冲突，不能静默取首条。

## 模型整理：明确授权后排队

`POST /preview` 接收：

```json
{
  "text": "在此填写本次需要整理的原始论文清单",
  "consent": true,
  "options": {
    "max_cost": 0.1,
    "max_output_tokens": 2048,
    "model": {
      "name": "deepseek-flash",
      "currency": "CNY"
    }
  }
}
```

本例费用上限为 0.1 元，只是演示请求字段。使用前根据真实文本规模、模型价格配置和输出预算确定上限。
`consent` 必须明确为 `true`；省略、`false` 或字符串均不能授权。
只将 `text` 提交给模型，不因传入分类名称而读取目录文件。此授权不包含标题翻译、全文获取或科研分析。

通过前置验证后返回 HTTP 202：

```json
{
  "job_id": "本次任务编号",
  "kind": "input_normalization",
  "status": "QUEUED",
  "downloads_started": false,
  "status_url": "/an-api/input-normalization/本次任务编号"
}
```

202 仅表示已加入任务中心，不表示模型输出已通过验证。继续按 `status_url` 查询，
无须再次发送 POST。服务切换文库时，旧任务捕获的工作区租约会重新检查，不能悄悄落到新文库。

## 查询任务和费用

`GET /{job_id}` 返回本类任务的状态、进度及允许公开的结果字段；不能用它读取下载、解析或科研任务。
仍需相同能力令牌。一般隔几秒查询即可，读取状态不会触发模型调用。

主要字段如下；任务尚未结束时，部分字段可能尚不存在：

| 字段 | 含义 |
| --- | --- |
| `job_id`、`kind`、`status` | 任务身份与真实运行状态 |
| `stage`、`current_index`、`total` | 当前阶段与可用进度 |
| `billing_uncertain` | 是否存在已发送但费用无法确定的请求 |
| `result.canonical` | 通过验证的规范输入，含 `papers` 和 `source_map` |
| `result.preview` | 共用获取预览，包括错误、重复和冲突 |
| `result.preview.library_path_validation_pending` | 模型侧仅完成相对目录字符串校验，尚需结合实际文库校验保存位置 |
| `result.calls`、`result.usage`、`result.accounted_cost` | 已记录调用、用量与费用估算；失败响应也可能已经计费 |
| `result.diagnostics` / `error` | 脱敏后的诊断代码及可读原因 |

接口过滤内部文件路径、来源工件定位、请求头、响应头和密钥，不把原始供应商响应直接作为成功结果返回。
不确定费用不能解读为零；请求失败也不能推导为未计费。确认原任务状态后，再决定是否显式提交新请求。
接口没有承诺重复 POST 幂等：相同文本再次 POST 仍可能创建新任务、再次计费。
若提交请求后连接中断且没有收到任务编号，先在 UI 任务中心核对，避免盲目重发。

## 规范结果与安全采用

规范结果采用 `aletheia-nexus/acquisition-input/v1`，不能只取一串 DOI 或按模型返回顺序重新配对：

- `papers` 是合法 `PaperRequest` 字段的逐篇字典，保留 DOI、原题及原文确实给出的书目信息。
- `source_map` 保留逐篇稳定编号、`paper_key`、从 1 开始的原文行号 `source_lines`、行标识及引用片段 `quote`。
  输入中明确出现的每次 DOI 均须有对应关系；模型不能增加原文不存在的 DOI 或静默漏掉原 DOI。
- `source_map.organization.folder` / `.tags` 区分原文明确值 `explicit`、模型建议 `proposed` 和未设置 `none`。
  模型建议仍需确认，不应被当作原文已经指定的分类。
- `source_map.assignment` 和 `preview.items[].assignment` 保留
  `folder_mode=inherit|custom|root`、`tags_mode=inherit|custom`。

`folder:null` 本身无法区分“继承默认”与“明确放到根目录”；`tags:[]` 本身也不能区分继承与明确清空。
**采用时保留完整 `source_map` 和已验证的 `preview`，不要仅把 `papers` 重写为普通 CSV/JSON 再推断这些模式。**
未设置组织字段才继承当前默认；根目录和无标签是明确覆盖。

模型服务本身不读取文库目录。`library_path_validation_pending=true` 表示规范结果的分类字符串虽合法，
仍需在当前授权文库中检查实际目标、已有文件、符号链接和目录联接；不能把这个预览当作文件写入授权。
UI 采用后仍进入同一目录选择和获取前检查流程。

模型输出不完成 DOI 身份核验：没有原文可靠 DOI 的条目可保留标题，继续走已有中英文标题解析及正文验证。
不接受模型编造的 DOI 或无出处书目字段。多个候选不唯一时，仍需人工确认。

这个 API 不提供“覆盖草稿”或“开始下载”端点。调用方应展示预览，
将 `input_sha256` 与原输入、当前草稿版本对照，用户明确采用后再进入既有获取流程。
等待期间若编辑了原文或草稿，先解决版本差异；不能用后返回的旧结果覆盖新编辑。
界面中的“确认采用并预览”同样只更新获取草稿，最后仍须检查范围并单独开始获取。

同批论文可有不同目录；同一论文仍是单个主存储位置。多研究范围使用标签或固定集合，
此接口不提供一篇论文复制到多个物理目录的功能。

## Windows 本地脚本示例

先把手动请求保存为 UTF-8 的 `manual.json`。在 PowerShell 中读取本次令牌，不必把它写进脚本：

```powershell
$baseUrl = 'http://127.0.0.1:8080/an-api/input-normalization'
$previewToken = Read-Host '粘贴工作台当前提供的本地接口令牌'
curl.exe --request POST "$baseUrl/manual" `
  --header "X-AN-Preview-Token: $previewToken" `
  --header 'Content-Type: application/json' `
  --data-binary '@manual.json'
```

确实需要模型且已同意费用时，使用上述模型请求结构保存为 `model.json`，将路径换成 `/preview`。
接着使用返回的编号查询：

```powershell
$jobId = '返回的job_id'
curl.exe "$baseUrl/$jobId" --header "X-AN-Preview-Token: $previewToken"
```

常见 HTTP 错误：403 为凭证或同源检查失败；413 为请求/文本过大；415 为内容类型错误；
422 为字段、文本、授权、模型或预算参数无效；404 表示没有这项规范化任务。
HTTP 请求成功后，模型失败通过任务状态和诊断表达，不能只检查 HTTP 状态码。
