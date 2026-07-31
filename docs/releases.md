# Releases & Rollback

We maintain **stable, manually tested releases** for safe production use.

## Finding stable releases

- **GitHub Releases**: all stable releases are tagged and published on
  [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
- **Latest tagged version**: the most recent stable version is marked as
  "Latest Release"
- **Changelog**: see [CHANGELOG.md](../CHANGELOG.md) for detailed change history

## Version policy

- **Tags starting with `v`**: official stable releases (e.g. `v2.0.1`, `v1.7.5`)
- **Main branch**: latest development code (may be unstable)
- **Testing**: all stable releases are manually tested before tagging

## Rolling back to a stable version

If you encounter bugs in a newer version:

**Option 1: Git rollback (recommended)**

```bash
# Check available stable tags
git tag

# Rollback to specific stable version (e.g., v2.0.1)
git checkout v2.0.1

# Then update your CODESYS scripts with that version —
# follow the installation steps to copy the files
```

**Option 2: Download from GitHub Releases**

1. Go to [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
2. Download the release archive for the stable version
3. Extract it over your program folder, then run `cts install-menu` to refresh
   the CODESYS menu scripts — see [Installation](install.md#method-2-manual-copy)

> [!NOTE]
> You can also use the [Quick PowerShell Setup](install.md#method-1-quick-powershell-setup-recommended),
> which downloads stable releases as clean zip archives without requiring Git.

> [!NOTE]
> Always back up your project before rolling back to a different version.
