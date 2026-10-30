# 溯光 (Aletheia Nexus) local research workbench user guide

[中文主文档](WORKBENCH_USER_GUIDE.md) · English translation

This guide covers v0.8.0 (updated 2026-10-30). Python 3.11 or later is supported; Windows is the primary acceptance platform.
GitHub Releases and the PyPI project page establish release identity; use the actual checked-out commit or installed package version. Engineering acceptance is documented in the [release acceptance record](V08_RELEASE_ACCEPTANCE.en.md).
Scientific extraction still has limitations in chart relationships, omissions, and condition assignment. Passing UI engineering checks does not establish scientific accuracy.
The latest ten-paper workflow comparison, historical reuse, source review, and statistical boundaries are documented in the [scientific comparison report](V08_TEN_PAPER_COMPARISON.en.md).

For a first run, follow the three steps under “十分钟开始” (Get started in ten minutes) on the home page. [Usability improvements and observations](WORKBENCH_USABILITY.md)
documents grouped pasted lists, mixed directories/tags, and an actual first import → parse → search → original-page workflow.

## Installation and first launch

Run once from the project source directory:

```powershell
python -m pip install -e ".[ui]"
aletheia-nexus ui --library "D:\文献库"
```

The local browser opens automatically at `http://127.0.0.1:8080` by default. Later, reuse the command or a launch shortcut you create yourself.
`.[ui]` includes the Playwright Python dependency but does not automatically download browser binaries.
AN first tries local Chrome/Edge or an existing AN runtime. Follow the UI instructions if the runtime is missing, its security version is incompatible, or configuration is invalid.
Institutional access still requires a valid, lawful session. Users perform login and verification; AN does not automatically bypass them.
Attachment download URLs may require separate login or verification: being able to open the main article does not mean SI access is cleared.
Keep the article and attachment verification pages open in AN's visible browser, then follow “Retrieve SI only” below.
Local OCR requires `.[ui,ocr]`, Poppler, Tesseract, and the relevant language data. Configure RapidOCR separately using the existing image-ocr instructions.
Original-page images also use the existing Poppler installation. Opening a complete browser PDF and downloading the original file are separate actions.

Use `--port 8098` to avoid an existing service, and `--no-open` to prevent automatic browser opening.
`--workspace` sets the directory for settings, tasks, caches, parse snapshots, and results. Its default is
`.aletheia-nexus/workbench/` beneath the launch directory. Only one task-manager process may use a workspace at a time.
The workbench binds only to `127.0.0.1`; there is no public-network or multi-user mode.

An existing AN library can be used directly as the root, without migration or downloading again. Change roots in Settings after active tasks finish.
Refresh other open pages after switching, so operations do not accidentally target the new library.

When a model is first needed, open “DeepSeek API 配置” (DeepSeek API configuration) at the top of Settings, enter a new key and the official base URL,
and click “保存 API 配置” (Save API configuration). By default the key is used only in the current process. Leaving it blank retains the current key, whose value is never displayed.
Windows optionally supports storing it in the user credential manager for this workspace. Other platforms use the session or environment variables;
`DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL` are also supported. Presets, tasks, logs, and exports do not contain keys or cookies.
“检查连接（不发论文）” (Check connection without sending papers) only queries the model list. It neither saves newly entered settings nor generates scientific content.
Wait for running tasks before changing configuration. Configuration alone does not verify authentication, balance, or model permissions.
Each remote workflow still needs its own authorization. Launching the application, browsing a library, parsing, and keyword search do not call a model by default.

New workspaces use the starting defaults below. Upgrades do not silently overwrite explicitly saved global settings or named presets.
New ordinary UI research tasks default to reading followed by assembly. Loaded tasks retain their strategy; legacy tasks omitting it still use direct single-pass extraction, as described under “AI research, results, and revisions.”

| Setting | New-workspace default |
| --- | --- |
| Acquisition sources | Public sources first, then institutional-browser fallback if unsuccessful; an environment API key does not automatically enable official API acquisition |
| Browser | Visible and interactive, using an independent AN session, selecting an available runtime automatically and following the system proxy |
| Human login and verification | Unlimited waiting; automatic recheck during main-text waiting is on and can be disabled in common settings. Explicit pauses still require resume. CAPTCHA and access permissions are not automatically bypassed |
| Batch scheduling | One second between ordinary papers; CNKI intervals and failure backoff follow the existing supported parameters |
| SI and parsing | Attempt SI; automatically parse successful main PDFs and linked PDF SI using native text first, without forcing replacement of old versions |
| File naming | Year-journal-Chinese title, falling back to the original title when no Chinese translation exists; original-title and custom templates are available |
| OCR and model fees | OCR off; title translation on import/acquisition off. AI input organization, title translation, and scientific analysis each require separate authorization |

Detecting Playwright only establishes that the Python dependency exists. It does not establish successful browser startup or institutional/publisher permissions.
Public-source success need not launch an institutional browser. Access blocks retain their actual failure status.

## Home page and in-application instructions

The application opens on Home. Based on the current library and real task records, it shows paper counts, linked SI, parse coverage,
the current selection, recent tasks, and saved results. An empty library presents starting actions rather than invented demonstration papers.
Home links directly to acquisition, library, search, and research. The selection list, task center, and settings are available at the upper right.

Click “阅读操作指南” (Read instructions) or “操作指南” (Instructions) in the top bar for offline help covering first use, acquisition, organization,
parsing/search, AI research, result checking, task recovery, and settings. Search the instructions for terms such as “中文命名” (Chinese naming), “SI,” “费用” (cost),
and “恢复” (recovery). Ordinary operations, parameter names, units, states, and common errors are shown in Chinese.
“原始诊断（专家）” (Raw diagnostics, expert) retains necessary original codes and redacted details for troubleshooting.

For first use, import one paper, open its original, add a tag, parse, and search before creating a research plan.
Local plan creation does not call a model. Title translation, model planning, and research execution separately confirm actual outgoing content and cost.

## Acquiring papers

1. Paste DOIs or Chinese/English titles on “获取论文” (Acquire papers), or select a TXT/CSV/JSON list. A whole classified/grouped list can be pasted at once, then processed using “手动整理并预览” (Organize manually and preview).
2. Check input errors, per-paper categories, and tags. Double-click a final directory or tag cell to open that paper's settings, or select rows and click “设置所选” (Set selected) for batch editing; both use the same dialog. Advanced columns optionally override individual base filenames. Check the final number enabled for acquisition.
3. Resolve/confirm English titles without DOIs first. Only a unique, exact candidate satisfying identity constraints passes automatically;
   other cases require a human choice. Chinese titles retain the CNKI bibliographic route and require applicable permissions and institutional-browser policy.
4. Set categories (new names are created safely), tags, collections, and naming templates; choose SI and automatic parsing as needed.
   Automatic title translation after acquisition is off by default. Enabling it still requires separate authorization for titles only and the batch cost cap.
5. New workspaces try public sources first and allow institutional-browser fallback; public-only acquisition is optional. Browser session, human-handling policy, automatic recheck, waiting time, ordinary intervals, attempts, and backoff appear in common settings.
   Request/navigation timeouts, CNKI intervals, route/candidate budgets, proxies, and similar options are advanced. Presets save actual values for reuse and editing.
6. After starting, view progress, current stage, and independent per-paper main-text/SI states on this page. Open “全部任务与历史” (All tasks and history) for full channels, failure reasons, directories, checkpoints, and recovery records.

### Progress on this page and login handling

Real task progress appears below Start. “查看获取任务” (View acquisition task) switches between recorded tasks for the current library.
Closing, refreshing, or leaving the page does not cancel background acquisition. Returning shows saved task and per-paper results.
If the process exits, unfinished tasks become interrupted. Review existing results and checkpoints before explicitly creating a recovery task; downloads do not restart automatically.

New workspaces allow institutional-browser fallback through an independent, visible AN session; opening a browser or filling advanced parameters first is unnecessary.
“检查本次浏览器配置” (Check this browser configuration) checks Python dependencies, a specified executable, and interactive settings. It does not initiate login or establish institutional access.
Check again after changing advanced browser settings. Actual launch still follows existing runtime, security-version, and access checks.
The new-workspace browser session defaults to `human-handoff`. Saved sessions in older workspaces, such as `default`, remain unchanged
across upgrades. Use the session shown in the current form. Changing sessions does not copy login data and may require a new lawful login.

Complete login or CAPTCHA in the visible institutional browser. “人工验证完成后自动检测并继续” (Automatically detect and continue after human verification) is on by default.
It applies only to main-text acquisition in the “等待人工登录 / 验证” (Wait for human login/verification) mode. When off, use “验证后继续” (Continue after verification) to request rechecking.
“立即重新检查” (Recheck now) also only triggers a check; it does not assert verification succeeded. A pause policy or explicit pause still requires manual resume,
even if the page becomes accessible. Skip or cancel if needed. Zero seconds means unlimited waiting; a positive value limits this wait.
While the browser is still waiting, continuation resumes the current attempt. If the paper has already returned a permissions-needed result, continuing at the paper boundary schedules subsequent papers only;
use “Retry selected failed papers / Retrieve SI only” later for that paper. Waiting is not acquisition success and does not bypass CAPTCHA, MFA, or subscription restrictions.
Pause and cancellation take effect at safe boundaries; transfers and authorized model requests already started may still finish.

Main-text progress counts paper requests; attachments and parsing count actual files, so a paper may have several SI files.
“All main texts verified” does not mean the task is finished: check translation, naming, or parsing and wait for its terminal state.
After each paper's main-text and SI attempts, the selected workflow translates missing titles, synchronizes main/attachment naming, and parses before starting the next paper.
These postprocessing failures retain their reasons without turning an already verified main text into an acquisition failure.
Even if the main text is verified and all physical pages have parse coverage, genuine warnings may make parsing and the overall task partially complete.
Inspect main text, SI, page coverage, and warnings separately. Do not download a verified main text again merely to clear the aggregate status. Page coverage is not scientific extraction accuracy.

Automatic title translation shares the **whole batch's** cost and request caps. Immediate per-paper translation usually needs at least one request for each new title, and retries also count;
for example, twenty allowed requests cannot cover twenty-five entirely new titles. Cached and protected translations need no new model requests, and the software does not silently increase the budget.
Unknown cost retains a reservation and blocks further new translation requests. Existing cache remains usable, naming can fall back to original titles, and source files/completed results remain preserved.

If the UI says “Main text succeeded; attachments need separate human login or verification,” complete it on the retained attachment page and keep that paper's article page open.
Attachment URLs may differ; neither an open main text nor an earlier login proves attachment verification. The software does not solve CAPTCHA automatically.
After the batch ends, choose “选择失败论文重试 / 仅补 SI” → “仅补 SI” (Retry selected failed papers / Retrieve SI only → Retrieve SI only), select the same browser session, review the actual scope, and confirm.
This revalidates and reuses verified main texts, retains their filenames, and attempts only incomplete attachments. Permission denial or continuing blocks remain explicit.
The SI stage currently does not automatically resume immediately after human intervention; use this reviewed retrieval entry point.
Automatic SI coverage is determined by independent results. Saving the main text does not guarantee SI acquisition.
Real retesting still encountered Wiley, RSC, and Elsevier official pages requiring human action with attachments not yet obtained.
“Not found” means this attempt found no supported entry point, not that the paper has no SI. Local attachments can be linked from paper details when necessary.

### The article opens, but the PDF has not been saved

Article pages, main PDF pages, and SI downloads may require separate login or verification. After verifying the article page,
check newly opened PDF or attachment pages for their own prompts. Reading the article does not establish that PDF transfer or attachment verification is complete.
Keep the article and related PDF/verification pages in the current AN browser session. Do not close the whole group or browser before retrying.

“阅读器已响应，PDF 尚未交付” (Reader responded; PDF not yet delivered) means the program received a PDF-reader page but has not obtained a verifiable PDF file to save.
It is not download success, nor does that message alone prove an authorization problem. Original diagnostics remain available for troubleshooting.
Only after receiving the file and verifying source identity does the main text display “来源已验证” (Source verified).

If the current attempt is still waiting, follow the selected automatic recheck or manual continuation policy. If it has failed,
complete the required page actions, wait for the task to reach a terminal state, and use the entry below to retry only that paper.
Manually saving a reader PDF does not automatically create a verified acquisition result. Import it under the source-record and local-import rules if needed.

### Retrying unsuccessful papers and retrieving missing SI

After a task ends, click “选择失败论文重试 / 仅补 SI” (Retry selected failed papers / Retrieve SI only) in page progress or the task center. The dialog checks current files, sources, and checkpoints,
then distinguishes unsuccessful main texts, not-started papers, valid main texts with missing SI, fully completed papers, and sources requiring review.
Only eligible unsuccessful items are checked by default. “只选这篇” (Select only this paper) clears other checks without executing immediately.
You may select several papers or use “仅补 SI” to select missing attachments. Review counts, save directories, original tags, and session, then click “开始重试所选论文 / 补 SI” (Retry selected papers / Retrieve SI).
For one paper, select its “只选这篇” action and confirm that the displayed retry count is one. Retain the original article/PDF pages and use the original browser session.
Changing the selected scope does not execute it or silently include unchecked failures.

With a verified main text and valid checkpoint, SI retrieval reuses the real engine's identity verification and main-text reuse rather than downloading the main text again.
After renaming or moving the main text, unique location still requires both PDF and source-record hashes; file existence alone is insufficient.
The original SI service checks and reuses existing attachments. Not-found, partial-failure, and incomplete-coverage outcomes remain explicit.

You may switch this retry to public sources plus institutional browser. Other timeouts, intervals, route budgets, per-paper directories, tags, and filename overrides retain their previous values.
A retry uses an independent checkpoint, preserving original checkpoint bytes and task records, and appears as a new task on the current acquisition page.
Paid title translation is not enabled again by default. Re-enabling it requires renewed titles-only transmission and cost authorization.

The same batch cannot be retried concurrently while its original task runs. With a missing checkpoint or nonunique source verification, older successes are marked for review;
they are not silently redownloaded from their old status. Restore the original materials or explicitly create a new acquisition request.

### Manual and model-assisted normalization of arbitrary text

Paste a list containing numbering, explanatory paragraphs, category headings, or citations, then organize it into per-paper acquisition previews.
**Organizing input, accepting it, and starting acquisition are three separate steps.** Organization does not download papers or automatically create category directories.

Without a model, click “手动整理并预览” (Organize manually and preview). Edit the source text as needed, using one DOI or full title per line,
and use the grouped headings, `分类=...`, and `标签=...` syntax below to specify organization. Manual preview makes no remote model call and incurs no model fee.
Local rules recognize explicit input rather than inferring scientific categories. Check that irregular citations or commentary were recognized as papers correctly.

For messy input requiring model-assisted splitting, use “AI 整理输入” (Organize input with AI):

1. Review the pasted text to send, model, and cost cap, then explicitly authorize the request. Only this pasted text is sent;
   selecting a library does not upload PDFs or the entire library. Normalization consent does not authorize later title translation or AI research.
   For long lists, “使用大批量整理建议” (Use large-batch suggestions) shows suggested output capacity and cost cap together for review, without requiring every advanced parameter first.
2. View progress and returned cost records in the task center. Closing the page does not revoke an issued request. Check unknown costs first;
   do not treat them as zero or repeatedly click Retry.
3. Check each DOI, complete original title, matching source-text location, category, and tags. Model suggestions do not verify paper identity,
   and an absent DOI suggested by a model is not established. Existing title resolution and main-text source verification still apply.
4. “确认采用并预览” (Accept and preview) transfers results into the existing acquisition preview. If the source text or current draft changed while waiting, resolve the version conflict first;
   do not overwrite new input with an old result. The original text remains the checking reference.
5. Continue editing categories, tags, and acquisition inclusion in the per-paper preview; check enabled counts and duplicate conflicts, then start acquisition separately.

“本批多个目录” (Multiple directories in this batch) on the right selects existing categories or new subdirectories per group. “单篇目录与标签” (Per-paper directory and tags) selects a paper for adjustment.
Directory/tag cells show final arrangements; double-clicking opens the same settings dialog, so no duplicate editing workflow is required.
The batch default directory applies only to papers without their own setting. Main/SI naming lists include “自定义模板” (Custom template). Edit the actual template, name and save it,
then reuse it from the list. Large-batch duplicate notifications consolidate counts; full source matches and the call ledger load in the expert area when expanded.

Review explicit source groupings and model-suggested categories separately; a suggestion is not a user-confirmed directory.
After accepting a preview, choose existing categories, new subdirectories, or restored inheritance. **Root directory** explicitly means no category subdirectory;
**No tags** explicitly means no tags. Neither means a blank that later inherits defaults again.

Different papers in a batch may use different categories. A paper still has one primary storage location. Use multiple tags or fixed research collections
to include it in several research scopes. Duplicate identities proposed in different directories become conflicts rather than duplicate downloads or main-text copies.

A failed model request does not start acquisition. If a result arrived but could not be accepted, first correct or reselect the existing preview locally,
avoiding a repeated paid request for a local organization issue. Programmatic integration is described in the [normalization API notes](WORKBENCH_NORMALIZATION_API.md).

### Saving papers in a batch to different categories

An already grouped A–D list of twenty-five papers can be pasted as a whole. Group headings are not papers, and numbered DOIs are not mistaken for titles without DOIs.
Groups read explicitly supplied directories and tags only; no AI or content-based category inference is involved. First confirm that preview finds twenty-five papers,
then check group categories, tags, and duplicates before starting.

The following demonstrates input syntax only. These DOIs are placeholders, not downloadable papers; replace them with your own:

```text
A. 电合成/羧酸还原 | 标签=待读,羧酸
1. 10.1234/example-a01
2. 10.1234/example-a02

B. 电合成/醇氧化
标签=待读,醇
3. 10.1234/example-b01

C. 表征方法
4. 10.1234/example-c01 | 标签=方法参考

D. 待整理
5. 10.1234/example-d01 | 分类=/ | 标签=[]
```

Papers inherit their group settings; explicit inline settings override the corresponding group fields. Fields without group settings inherit the defaults in the right-hand form.
The final paper above explicitly uses the library root and no tags, even if default category or tags have values.

Other explicit formats are supported:

- Bracketed categories, such as `[电合成/羧酸还原]`; a heading may include `| 标签=待读,羧酸`.
- Markdown hierarchy: `## 电合成` followed by `### 羧酸还原` produces relative directory `电合成/羧酸还原`.
- No groups: one `DOI | 分类=电合成/羧酸还原 | 标签=待读,羧酸` per line. Tabs may also separate fields.

`分类=/` or `分类=根目录` explicitly selects the library root. `标签=` with nothing after the equals sign, `标签=空`, `标签=[]`, and `标签=无标签`
all explicitly mean no tags. Omit the whole field to inherit. `分类=` cannot be empty; omit it to inherit the category.
Inline tags replace group tags. Directories are always relative to the current library;
absolute paths or `../` cannot escape it. Syntax/directory errors report line numbers, and an invalid group does not silently inherit the preceding group.

### Selecting and batch-editing after preview

Select rows in preview before applying category or tag operations. Editing scope and acquisition scope are displayed separately:

- **Selected rows** determine which papers this batch edit changes, without automatically changing acquisition inclusion.
- **Acquisition status** determines which papers are submitted on Start. Change it using enable/disable selected papers. Unselected but enabled papers are also acquired.

Categories can retain per-paper settings, restore default inheritance, use one explicit relative category, or explicitly select the root. Tags can retain settings, restore inheritance,
replace, append, remove, or clear. Append/remove uses each paper's actual current tags, preserving per-paper differences. Applying it creates an independent override;
later default-tag changes no longer alter that row. Choose inheritance if it should continue following defaults.

| Intent | Setting to use | Effect of later form-default changes |
| --- | --- | --- |
| Follow this batch's default category or tags | Inherit defaults | Affects rows still inheriting |
| Keep a paper's independent category or tags | Per-paper override / explicit value | Does not change that override |
| Store at library root | Explicitly choose root | Does not restore the default category |
| Give this paper no tags | Explicitly clear tags | Does not restore default tags |
| Leave this field unchanged in this operation | Retain per-paper settings | Retains its inheritance or override mode |

Blank input must not simultaneously mean both inherit and clear. Use explicit root/no-tag actions and verify actual preview categories and tags.
DOIs, titles, and individual filenames in advanced columns are directly editable; directories and tags use the same per-paper/selected-paper settings dialog.
After editing a cell, you can click a batch operation or Start directly. The UI commits the current cell edit before reading batch parameters.

Identical identities with identical settings are reported and deduplicated. The same DOI in different categories or with different tags is explicitly a conflict,
not silently resolved by taking the first, merging tags, or downloading two copies. Retain the correct settings, disable duplicates, then check enabled counts.
Editing a DOI or accepting a title candidate after preview can introduce duplicates, so Start checks again. Input deduplication does not replace verification of existing files.

### Browsing categories and creating subdirectories

The default, batch, and per-paper category settings on acquisition open “选已有目录 / 新建子目录” (Choose existing directory / Create subdirectory). Local PDF import uses the same selector.
The tree includes existing empty categories, supports name search, entering children, and moving up, and shows relative and complete save paths.

To use an existing category, select it and click “使用选中目录” (Use selected directory). To create one, choose an existing parent, enter one child-directory name, review the proposed path,
then click “新建子目录并使用” (Create subdirectory and use). Opening the selector or entering text does not create a directory. Files are not overwritten; simply select an existing same-name directory.
Library root is an explicit option returning an empty relative path, rather than an extra directory level.

The tree enumerates directories within the current authorized library only and does not read PDF content. `SI/`, `json/`, internal-data directories, symlinks, and Windows junctions are not categories.
The default limits are 1,000 displayed directories including root, 24 levels, and 20,000 examined entries. Reaching a limit explicitly reports an incomplete listing.
For many directories, enter and validate an existing relative path directly. Search covers loaded directories only, not unenumerated portions.

Successful title resolution is not successful PDF acquisition. Only main texts verified by the existing trusted engine show “来源已验证” (Source verified).
Automatic SI supports explicit official attachment links on DOI-matching pages. PDF SI is stored with an explicit parent as a locally declared identity,
not presented as main-text verification. SI failure does not invalidate a verified main text. See
[acquisition and SI support](WORKBENCH_ACQUISITION.md) for coverage.

Main texts are flat within each category; attachments share its SI directory:

```text
文献库/羧酸还原/
  2026-期刊-论文甲.pdf
  2025-期刊-论文乙.pdf
  SI/
    2026-期刊-论文甲__SI-01.pdf
    2026-期刊-论文甲__SI-02.xlsx
    2025-期刊-论文乙__SI-01.pdf
  json/ ...原始来源与独立标签记录...
```

Filenames do not establish linkage; parent identity and hashes link main text and SI. Each category has its own `SI/`.
Research-report abstracts, source data, peer-review files, and actual SI are registered separately.

## Organizing the library and batch Chinese naming

“文献库” (Library) imports PDFs/folders, selects existing roots, and searches original titles, Chinese translations, display names, DOIs, and filenames,
with category, AND/OR tag, fixed-collection, and untranslated filters. Double-click a paper for metadata, attachments, provenance, and PDF.
Parse status filters include complete, partial, failed, and unparsed, and are restored with saved filters.
Expand “来源、缺失文件与重复副本诊断” (Source, missing-file, and duplicate diagnostics) below the list to inspect actual problematic paths and reasons without a terminal.

Multiple automatically verified main-text sources sharing both DOI and PDF fingerprint display as one paper by default. Different PDF versions and locally declared sources are not merged.
Original source IDs, files, parse versions, and each source's SI remain intact. Double-click to inspect each source, or switch to per-source rows.
Directories, tags, and collections filter original sources before display grouping. Selecting a row includes only explicitly matching sources, not other unselected copies.
When new parsing, local planning, or remote planning selects several sources from the same group, choose the one actually intended for this run, with path, authors, parse status, and attachments shown.
A single selected source or unrelated papers require no extra choice. Canceling creates neither a task nor model calls and leaves the selection list and history unchanged.

The header checkbox or “全选当前页面” (Select current page) selects only that page. “加入全部筛选结果” (Add all filtered results) handles all matching papers and displays the actual count.
“加入选择清单” (Add to selection list) adds checked papers to a global list for accumulation across pages, deduplication, removal, collection saving, parsing, or research.
“解析已勾选” / “检索已勾选” (Parse/Search checked papers) operates on the current table checks without changing the cross-page selection list; the UI displays both scope counts separately.
Apply search with Enter. Clear filters to see the full library again, and refresh/apply filters after material changes.
Selecting papers does not mean all attachments are automatically uploaded. Confirm main-text/SI scope before AI execution.

Five concepts are stored separately: original bibliographic title, model/human Chinese translation, custom display name, physical filename, and category directory.
Changing a display name is not a disk rename. Tags are mutable metadata; collections hold explicit members, saved filters hold conditions, and views hold presentation choices.
Changing collections or tags does not change historical research inputs.

### Adding Chinese titles directly

Check one or more papers in the library and click “补中文标题” (Add Chinese titles), without opening batch rename.
The untranslated filter finds papers lacking translations. Paper details offer the same action.

- For one paper, enter a title directly under “手动填写 / 修改（不联网）” (Manual entry/edit, offline), check it, and save. For multiple papers, select individual items there to fill them in.
- Batch mode defaults to filling missing Chinese titles only and retaining existing translations. Inspect processing, cache-reuse, and outgoing counts. Human-edited or confirmed translations remain protected.
- For model use, review the model and request/cost caps, authorize only these original titles, then start translation/cache reuse. PDFs, body text, and the whole library are not sent; an entirely cache-reusable batch needs no paid-request authorization.
- Save parameters as a title-translation preset. Loading one or changing scope requires renewed transmission consent. Model, timeout, interval, and cache-retranslation controls are advanced.

The dialog shows translation status; the task center shows per-paper results, cache, and cost records. Closing it does not cancel submitted tasks.
For failure or unknown cost, inspect the cause before retrying repeatedly. Human translations added while queued or running are protected from model overwrites.
Saved titles update the library display. Original titles, document identity, PDF bytes, and physical filenames remain independent.
To use a translation as a disk filename, preview and execute an actual file operation in “整理已勾选文献” (Organize checked papers).

New-workspace acquisition naming defaults to year-journal-Chinese title, falling back to the original title without automatically buying a translation.
The naming list includes year-journal-original title; actual templates can be edited, named, and saved. Existing global preferences are not silently overwritten.
Only name presentation removes known paired formatting tags such as `<sup>` and `<sub>` and decodes entities: `Ti<sup>3+</sup>` becomes `Ti3+`,
and journal `&amp;` becomes `&`. Scientific text inside tags remains, and mathematical comparisons are not broadly stripped.
This does not change original titles, human translations, or translation cache; it triggers no retranslation or automatic file organization. Preview and execute renaming for existing names explicitly.

### Importing existing materials and explicitly linking SI

Use the plus button or drag PDFs into the upload area. For a whole folder, click “从电脑选择文件夹” (Choose folder from computer),
navigate disks/common locations in the graphical selector, and choose the current folder after entering the target. No manually transcribed path is required.
The selection fills the source and expands “已选文件夹与路径” (Selected folder and path). Check subdirectory inclusion, then click “开始导入” (Start import).
Alternatively paste an absolute PDF/folder path in that area. Start import performs the import rather than opening a selector.
With an empty path, the button is disabled. Paired quotes copied with Windows paths are accepted. Check “包含子目录中的 PDF” (Include PDFs in subdirectories) for nested files.
Nonexistent paths, non-PDFs, no top-level PDFs, and no PDFs even after recursion receive distinct messages. An empty path does not become the program directory.

An existing AN library may be selected directly as root. Importing from a local path containing source JSON preserves the original file;
valid source records are copied byte-for-byte, retaining verified or human-declared identity rather than redeclaring it.
Uploading only a PDF through the browser cannot read its neighboring source JSON, so it imports as human-declared identity.
To preserve AN verification, open the original library directly or import from a local path carrying its source record.
The source record determines the original title. Supplying a different title warns rather than overwriting the bibliography. Duplicate identities reuse the existing paper.
Only PDFs lacking a source record are registered as human-declared local papers using the supplied title and DOI.

Link existing SI as follows:

1. Double-click its parent main paper and expand “添加本地 SI / 其它关联附件” (Add local SI / Other linked attachments).
2. Enter the attachment's absolute path or upload a local file. Confirm that the displayed main paper is its actual parent.
3. Select the true role: SI, source data, research-report abstract, peer-review material, or other attachment. An attachment title is optional.
4. Click “登记到当前论文” (Register to this paper), view the task result, and refresh paper details to inspect the link.

Copies are stored in the unique `SI/` directory for the main paper's category, using its actual base name and sequential attachment numbers; extensions are retained.
Repeated import of the same attachment reuses a verified record. PDF SI can then be parsed, searched, and selected for research with the main paper.
Other roles and non-PDF attachments are safely stored and registered only; parsing or automatic opening is not promised.
The local attachment limit is currently 200 MiB, accepting supported document, data, image, and media types. Attachments are not executed and archives are not unpacked.

Ordinary PDF/folder import cannot turn known SI into an independent main paper. If provenance already names another parent,
the workbench rejects reassignment and explains why. Choose the correct parent; renaming files or overwriting provenance is not a linkage repair.
Thus recursive import of an old folder mixing main papers and SI may import main papers successfully while reporting known SI separately,
which must then be linked from the correct paper details. Partial completion does not mean every file entered the library.

### Tags, groups, and library-wide changes

“标签与分组” (Tags and groups) adds/removes free tags on the current selection list and maintains optional groups.
Typing a tag suggests existing tags; Enter creates one. Multiple selection and comma-separated batch input are supported.
Library-wide tag rename/delete affects all relevant papers in the current library and updates tag conditions in groups and saved filters.
Renaming can merge with an existing tag. Deletion does not alter PDFs, immutable provenance, fixed collections, or historical task snapshots.

Before executing, check whether the scope is the current selection or the whole library. Deleting a tag used in a saved filter reduces its constraints
and can broaden future matches. Inspect that filter again before creating a new research material list.

### Managing fixed collections, saved filters, and tag groups

The library toolbar's “管理集合 / 筛选 / 分组” (Manage collections / Filters / Groups) maintains these separate membership, filtering, and tag-organization objects.
For a fixed collection, use current table checks or the global selection list to replace, append, or remove members.
Preview old/new counts and the specific added/removed papers, then explicitly confirm. With no papers selected, membership cannot be changed arbitrarily.
Collection renaming updates saved-filter references. A collection referenced by saved filters cannot be deleted directly; the UI lists those references.
Adjust them first, then preview deletion again. Stale previews must be regenerated and cannot overwrite a newer state produced elsewhere.

Saved filters can adopt current library conditions or run directly. Editing a tag group's tags does not change paper tags.
These operations do not alter physical PDFs, provenance, or old research tasks. To change research scope, explicitly create a new task from the updated collection.

Enter batch organization through “整理已勾选文献” (Organize checked papers) or the selection list:

1. Choose a template supporting `{year}`, `{journal}`, `{first_author}`, `{title_original}`, `{title_zh}`, and `{custom_name}`.
   Category destinations explicitly distinguish keeping the current category, moving to a specified category, and moving to library root; attachments moved to root use its shared `SI/`.
2. For missing Chinese titles, choose DeepSeek translation, skipping, or original-title fallback. Review cache/human translations and budgets;
   calls require both title-transmission and cost authorization. Even unconfirmed human edits are protected against batch model overwrites.
   Load translation presets into the actual form, then confirm this transmission and budget again. Forced retranslation does not automatically carry over consent.
3. Generate complete previews for main papers and all attachments. Check old/new paths, shared-category SI paths, translation provenance, missing fields, conflicts, and executable counts.
4. Adjust individual final base names or exclude papers, then regenerate preflight and execute the real file transaction after review.
5. Inspect task-center results and file-operation logs. For interruption/failure, follow logs for verified rollback rather than manually moving hidden staging files.

Source evidence and old parsed artifacts remain byte-identical. New research materials use independent snapshots, so old tasks can continue after renaming.
If historical contracts or old CLI checkpoints cannot be safely relocated, the item is rejected with the risky files listed rather than silently rewritten.
Workbench acquisition checkpoints support hash-bound copy relocation. Arbitrary historical references outside authorized directories cannot be discovered automatically.
Transactions currently require one library root and a filesystem supporting hard links; cross-volume moves are unsupported. Exceptions roll back or explicitly require recovery.
Paths exceeding the portable 240-character threshold are blocked. Preview explains normalization of illegal characters and overly long base names.

## Table views

Built-in views cover standard literature, file organization, acquisition management, and research processing. Use “列/排序/视图” (Columns/Sort/View) to choose columns and save a named view.
Drag headers to change order/width and click to sort; changes persist automatically. The title column can be pinned and long titles wrapped.
Settings offer two-line Chinese/original titles, Chinese-first, original-first, and custom-short-name-first display.
Custom views also save their title preference; only older views lacking it use the global default.
Checkboxes occupy a separate fixed column, so multi-select still works with only original/translated titles and the display-title column hidden.
Missing metadata remains blank rather than inventing authors, years, journal abbreviations, or parse accuracy.
File integrity indicates fingerprint consistency. Source identity distinguishes local declaration from trusted acquisition verification; they are separate concepts.
OCR status distinguishes disabled, configured but unverified, and actually used. Research-task columns show only existing real links.

## Parsing, search, and evidence

Batch parse a filtered scope, fixed collection, or current selection list. Reuse trusted old artifacts or explicitly create a new parse version;
old versions are not overwritten. Configure native text/OCR, languages, DPI, page/block/resource limits, paragraph merging, and related settings.
Complete, partial, and failed parsing, page coverage, warnings, errors, parser versions, and source checks are shown separately.

Research search chooses scope, category/tags, main text/SI, sections, AND/OR, or exact phrases. Evidence view displays paragraphs, tables, and captions;
paper view groups the current page's evidence by paper. Coverage and total hits remain visible. A displayed page is not the full set of relevant papers.
A paper grouped from several sources retains all actual matched sources/evidence on that page. Evidence view and export retain original individual hits; presentation grouping does not replace material identities.
Material-check counts include main texts and SI in the selected scope and need not equal the number contributing hits after source-role filtering.
Switching paper/evidence views clears old page selections; select again. Leaving and returning retains this client's criteria, and clicking Search reruns them.
No hit does not establish that a paper did not report something. A translated-title hit is not semantic search of Chinese body text.
Selected hits can enter the selection list or research, be exported as original evidence, or open the corresponding physical PDF page.

## AI research, results, and revisions

After selecting papers, enter a natural-language goal in “AI 研究” (AI research). Generate a local plan first with zero model calls, or explicitly authorize
DeepSeek planning using the goal and metadata. Planning authorization is separate from sending paper contents.
Before execution, edit actual materials, fields/types, task type, steps, comparison, text/selected-page image mode, model, and token/image/
call/cost budgets. The expert area exposes the complete contract, but the ordinary workflow does not require a JSON file path.

New ordinary UI tasks default to the validated net-beneficial reading-then-assembly strategy. Direct single-pass extraction remains available; both reuse the same research engine.
Loaded tasks retain their explicit strategy. Legacy tasks omitting it continue as direct single-pass extraction rather than migrating to the new default.
Standard reading-then-assembly usually needs at least two model requests per paper. Cross-paper comparison, extra page reading, and retries count separately; cache can reduce new calls.
Choose sufficient request/cost limits. The program does not raise them for you. Strategy is saved in tasks and presets, with old choices preserved on load;
after changing it, preview again and review scope/authorization. Retired field-independent reading is neither an ordinary option nor silently substituted during execution.
The default strategy does not enable remote permission. Local preparation still uses zero model calls; metadata-planning and content-transmission consent remain separate.

Actual inputs are fixed snapshots of PDFs, provenance, and parse versions. After changing a plan, validate again and authorize remote content transmission for this scope.
Models may return insufficient-material, missing-SI, partial-result, or failure states. These are actual states, not guarantees of scientific completeness.
Paid failures are not automatically resent by default. Unknown billing retains a budget reservation; review it before creating a recovery task using the historical contract.

“研究成果” (Research results) places structured fields, claims, steps, and diagnostics on the left and PDF evidence on the right. Select data and choose “核对证据” (Check evidence) to locate the physical page;
SI uses its own page numbering. Original-page images and region enlargement support checking, while the complete PDF opens separately.
“人工修订/确认” (Human revision/confirmation) edits values and applicable conditions, records author and reason, and saves a new version while retaining the original.
For changes involving an automated assistant, choose “AI 辅助修订” (AI-assisted revision). It prohibits human confirmation, makes no model call, and does not record assisted checking as expert confirmation.
Replacing complex citations or entire procedural structures still uses expert editing. Ordinary values, original readings, units, states, and conditions do not require handwritten JSON.
Human confirmation is a separate explicit choice; a resolvable citation or contract-valid model output must never automatically select it.
Export supports Markdown, CSV, JSONL, and necessary task/version information, with historical scope reusable for a new task.
Each export also provides a ZIP containing native results, tasks, material manifests, revision history, and hashes. It does not include every original PDF;
complete backup still requires both library and workspace. Reading existing results and offline export make no repeated model calls.

## Unified task center and settings

Closing or refreshing a page does not cancel background tasks. Pause waits for the current indivisible operation; “Paused” appears only at a safe boundary.
Cancellation also waits for safe boundaries. Issued HTTP/model requests may have occurred or incurred fees and cannot be treated as revoked.
When institutional login/verification is needed, explicitly continue, skip the current item, or cancel; CAPTCHA, MFA, and subscription restrictions are not automatically handled.
After process exit, unfinished tasks become interrupted with completed items and checkpoints preserved, without restarting themselves.
Transaction logs record restored and pending items and conflict reasons. Rename preview scans historical references in the background;
it does not mean files moved. Only confirmed execution commits the disk transaction. Results and recovery records remain available in the task center.

Ordinary errors provide a Chinese cause and suggested next step. File locks, naming conflicts, historical-reference risks, and unknown fees need distinct handling;
do not repeatedly click Execute to probe them. Unrecognized errors retain redacted raw expert diagnostics.
Missing records, inconsistent sources, and insufficient budgets are not displayed as success.

Common settings appear on task forms; timeouts/OCR/budgets appear in advanced panels; low-level parameters and full contracts are in expert areas.
Global defaults, named presets, and temporary overrides are saved separately. Presets contain parameter combinations, not keys or cookies.
Settings diagnose Python, browsers, Poppler/OCR, and API configuration. Missing dependencies produce actual errors rather than false success.
The ordinary diagnostic table lists components, real status, purpose, and next steps, with raw details expandable in the expert area.
API configuration shows only whether a key exists and its source, not the key. Detecting Playwright or a key does not mean browser, institutional access, or model requests were successfully tested.

## Support matrix and follow-up

| Capability | Current support | Boundary |
| --- | --- | --- |
| Local NiceGUI installation/startup, home/help, five business pages, global tools | Implemented | Single user, `127.0.0.1` |
| DOI/English-title/CNKI/institutional parameters | Existing capabilities adapted | Real institutional login requires lawful accounts; no fabricated acceptance claim |
| Official SI, multiple attachments, shared-category layout | Generic pipeline implemented; publisher coverage partial | DOI/version and explicit official-link gates. If needed, the allowed session may open its own missing article page; existing user pages are observed only. Not-found, challenges, and nondelivery are not success |
| Automatic main-text waiting recheck and human pause | Implemented; common-setting toggle | Main-text waiting only. Explicit pauses require resume; SI challenges retain pages and require reviewed SI-only retrieval |
| Retry one/several failures or retrieve SI only | Implemented | Confirm actual scope and revalidate. Valid main texts are reused, SI retrieval keeps main filenames, and paid translation is not silently repeated |
| Explicit local SI/attachment linkage | Implemented | Human-selected parent; type/size limits; non-PDF attachments not automatically parsed |
| Free tags, groups, library-wide rename/delete | Implemented | Tag deletion may broaden saved filters; historical tasks remain unchanged |
| Independent translation, cache, human protection, per-paper postprocessing | Implemented; shared-budget behavior has deterministic regression coverage | Immediate translation shares batch request/cost caps; unknown billing is not automatically resent. An earlier real end-of-batch call is not fresh real per-paper acceptance; estimates are not provider bills |
| Same-PDF paper display grouping and original-source choice | Implemented | Original identities/SI are not merged. Research selects actual sources within the selected scope, without changing historical inputs |
| DeepSeek session configuration / Windows user credentials | Implemented | Explicit saving required; other platforms lack this credential persistence. Configuration does not authorize transmission |
| Actual batch rename/move, logs, rollback | Implemented | Same root/volume. Scientific-format cleanup affects new-name presentation only, not provenance/translations; unsafe historical references are explicitly rejected |
| Custom columns/width/order/sort/views | Implemented | List cache is not a content-search index |
| Parse versions, OCR configuration, keyword search | Implemented | OCR needs optional tools; no semantic-recall guarantee |
| Plan editing, consent, snapshots, execution, history | Implemented | Unknown billing is not automatically resent |
| Split evidence view, region images, revisions, export | Implemented | Images require Poppler; no precise text-coordinate highlighting or full annotation system |
| Semantic/vector libraries, ELN, general-purpose Agent, multi-user cloud | Outside this scope | No complex system added for hypothetical future needs |

Acceptance details, platforms, and known limitations are in the [original acceptance record](WORKBENCH_ACCEPTANCE.md) and
[latest normalization, SI, and scale increment](WORKBENCH_NORMALIZATION_ACCEPTANCE.md). The latter distinguishes actual attachment downloads,
normal article-page observations, blocked access, and pending human actions; it does not combine them into universal publisher support. Back up both the library
(including `json`, `SI`, and `.an-workbench`) and workspace (snapshots, parses, tasks, results, and translation cache),
not merely a PDF filename list. Restore the same directory layout first; explicit historical paths moved elsewhere require relocation checks.
