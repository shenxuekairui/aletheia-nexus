# v0.8.2: startup experience and local storage management

[中文](RELEASE_NOTES_v0.8.2.md)

These notes describe the v0.8.2 source. They do not establish publication on PyPI or GitHub Releases.

- Default workspace and library paths use the user's home directory, avoiding writes beneath launch directories such as `C:\Windows\System32`, without administrator privileges.
- Settings → Data storage management displays and changes library, JSON index, and workspace locations, with folder selection, opening, copying existing data, or starting with an empty folder.
- Migration copies and verifies every file while retaining originals. Nonempty or overlapping targets, active tasks, and copy failures prevent switching. Restart after success so old sessions cannot continue writing.
- CLI/UI/MCP share user-level path preferences: explicit arguments, then saved locations, then defaults. `--library-state-dir` selects the JSON index separately. MCP adds `get_library_catalog` for the shared registry and collections.
- Existing v0.8.1 JSON layouts remain supported. Scientific artifacts retain their bytes; relocation mappings resolve historical absolute locators. Papers, metadata, tasks and results remain usable. Persisted Windows credentials are copied to the new workspace's user-credential target, never to data files.

Recommended PowerShell launch:

```powershell
aletheia-nexus ui --library "$env:USERPROFILE\AN-Library" --workspace "$env:USERPROFILE\AN-Workspace"
```

Omitted arguments use saved locations or `~/.aletheia-nexus/library` and `~/.aletheia-nexus/workbench`.
Visit `http://127.0.0.1:8080`. Restart the service after closing it; no reinstall is needed.
After migration, remove old explicit path arguments or update them.

On upgrade, first launch from the original directory or specify the old `--workspace`, then migrate in Settings.
See the [workbench manual](WORKBENCH_USER_GUIDE.en.md#data-storage-management) and [engineering acceptance](V082_STORAGE_ACCEPTANCE.en.md).
