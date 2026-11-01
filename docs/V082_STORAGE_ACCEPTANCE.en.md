# v0.8.2 startup and storage acceptance

[中文](V082_STORAGE_ACCEPTANCE.md) · 2026-11-02

## Scope and cause

Baseline: latest public v0.8.1 main, `403514f`. Branch: `feat/v0.8.2-storage`.
The UI used `Path.cwd()` for workspace and fallback library defaults. Launching from Windows System32 attempted to create data in a protected directory.
Library preferences also lived inside the workspace, making them difficult to locate after changing it.

The fix reuses the home-directory convention and atomic JSON writer. Three location pointers and relocation mappings live independently of the workspace.
Native JSON layouts, acquisition, parsing, retrieval and model strategies remain in place.

## Files and interface

- `storage_paths.py`: shared defaults, precedence, legacy discovery and relocation mapping.
- `ui_cli.py`: startup resolution, separate index argument and session protections.
- `workbench/storage.py`: empty-target checks, verified copying, original retention, native/MCP owner-lock checks, atomic switching and persisted Windows credential target copying.
- `workbench/ui_storage.py` and `ui.py`: Settings → Data storage management, purposes and complete paths, folder picker, opening folders, migration/empty-folder choices, progress and restart messages.
- `workbench/jobs.py`, `workbench/research.py`, `research_app.py`: submission protection and historical locator projection without changing canonical scientific bytes or widening allowed roots.
- `cli.py`, `mcp_server.py`: shared locations and `get_library_catalog` for the existing native registry.
- `pyproject.toml`: version 0.8.2.

The settings dialog shows the library, JSON index and workspace. Changing a location offers “迁移现有数据并切换” (copy existing data and switch) or “使用新的空目录” (use an empty directory).
Success updates displayed paths, prevents further session writes and requests a restart.

## Paths and compatibility

| Data | Default without saved preferences |
| --- | --- |
| Library | `~/.aletheia-nexus/library` |
| Index | `<library>/.an-workbench` |
| Workspace | `~/.aletheia-nexus/workbench` |
| Independent path preferences | `~/.aletheia-nexus/storage-paths.json` |

Examples: `C:\Users\carey\.aletheia-nexus\workbench`, `/home/carey/.aletheia-nexus/workbench`, `/Users/carey/.aletheia-nexus/workbench`.
Explicit CLI arguments override saved locations, which override defaults. Explicitly choosing an original copy is respected instead of following its historical move.

```powershell
aletheia-nexus ui --library "$env:USERPROFILE\AN-Library" --workspace "$env:USERPROFILE\AN-Workspace"
aletheia-nexus ui --library "D:\AN-Library" --library-state-dir "D:\AN-Index" --workspace "D:\AN-Workspace"
```

Omitting the workspace uses saved preferences or the user-level default. Visit `http://127.0.0.1:8080`; restart the service after closing it, without reinstalling.
After migration remove old explicit arguments or update them. First launch from the old directory recognizes an existing v0.8.1 workbench settings file, or supply the original workspace explicitly.
Existing `.an-workbench/library.json`, tags and collections remain supported; unknown old locations are not guessed.

## Migration checks

Copying preserves originals and verifies source/target SHA-256. Targets must be empty and must not overlap current data.
Failure keeps the old pointers active. Partial copies remain available for diagnosis. Active workbench tasks and native research/MCP owner locks prevent migration;
other processes should not start new writes during copying. Nested indexes travel with their library; separate indexes can move independently.

Verified scenarios include:

- All three locations separately: papers, attachments, tags, collections, custom names, parsed versions, task history and canonical research results remain readable and exportable after reopening.
- Original copies made unavailable by renaming test folders: new locations continue to work.
- Actual Windows C→D migration of library, independent index and workspace, including PDF, tags, collections, parsing, task history and result export.
- Empty-directory switching without copying or overwriting.
- Rejection of nonempty, overlapping, identical, file and relative targets.
- Copy errors, hash mismatches and preference-write failures keep originals and previous configuration; task submissions become available again.
- Active UI and native/MCP task ownership prevents switching.
- A fake Windows credential backend confirms old/new target availability and no secret in JSON.
- Actual MCP SDK stdio reads the separate saved registry, tags and collections; explicit allowed roots remain authoritative.

## Windows and test results

Windows, Python 3.14.3, NiceGUI 3.18.0. The acceptance process reports `IsUserAnAdmin() == False`.
A real HTTP service starts from `C:\Windows\System32` with user-level paths. Actual `C:\Users\carey\Desktop`, `D:\`, and `F:\` launches return HTTP 200 with identical defaults; explicit paths are respected.
The wheel installs into an isolated package directory, reports `aletheia-nexus 0.8.2`, and exposes UI/MCP help. Installed-wheel startup and C→D acceptance: **2 passed**.
All 223 Python source files in the wheel match the final checkout byte for byte.
Wheel SHA-256: `2285c1379f278441de1c72b635b8289715b36e69b433705d77bee5678d9150ec`.

Final full-suite result: **3988 passed, 148 skipped, zero failures, 456.90 seconds**.
The [complete test output](validation/v082-pytest.txt) preserves the original result. Ruff, compileall, `git diff --check`, and local-link checks across 12 changed documents passed.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q --tb=short --junitxml=acceptance.xml
python -m ruff check src tests
python -m compileall -q src
git diff --check
```

An earlier full run passed **3984 tests with 148 skipped**; focused retesting before the final boundary additions passed **34 tests**.
The 148 existing conditional skips concern opt-in browser smoke tests, external OCR and Windows symlink privileges. Skips are not passes.
No new live paper acquisition or paid model calls were performed, and no improved scientific accuracy is claimed.

## Documentation and limitations

Chinese/English README, installation/user manual, workbench guide, CLI/MCP guide, v0.8.2 notes and this report are updated.
Source and a local wheel do not establish publication; existing release history remains intact.

Actual visual inspection was not completed. Tool-driven navigation carried a cross-site marker and was rejected by the existing loopback guard.
Windows desktop control then stopped because it could not reliably determine the current browser URL.
The [computer-use skill](C:/Users/carey/.codex/plugins/cache/openai-bundled/computer-use/26.1021.31345/skills/computer-use/SKILL.md)
references the [stop rule](C:/Users/carey/.codex/plugins/cache/openai-bundled/computer-use/26.1021.31345/docs/guidance.md):
“If Computer Use reports that the turn ended or that the user stopped Computer Use, stop issuing app input.”
No further desktop input or protection bypass was attempted. In-process widget tests cover both options, displayed path updates, open-folder callbacks and folder selection.
Actual Windows processes/filesystems cover startup and migration; these are not described as human visual acceptance.

Merge judgment: **the change meets code-merge conditions; merging is recommended**. This is supported by the full regression suite, widget interactions, non-administrator Windows startup and actual cross-volume migration. The visual-inspection limitation remains documented; a human UI inspection is recommended before publishing. Local delivery does not include pushing, merging or publishing.
