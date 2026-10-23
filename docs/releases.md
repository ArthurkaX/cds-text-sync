# Releases & Rollback

We maintain **stable, manually tested releases** for safe production use.

## Finding stable releases

- **GitHub Releases**: all stable releases are tagged and published on
  [GitHub Releases](https://github.com/ArthurkaX/cds-text-sync/releases)
- **Latest tagged version**: the most recent stable version is marked as
  "Latest Release"
- **Changelog**: see [CHANGELOG.md](../CHANGELOG.md) for detailed change history

## Version policy

- **Tags `vX.Y.Z`**: stable releases (e.g. `v3.4.1`)
- **Tags with a suffix** (e.g. `v4.0.0-beta.3`): pre-releases; the installer
  does not list them, `main` carries the latest (a Git clone checks out the tag)
- **`main` branch**: the quick installer's default; now the 4.0 beta
  ([Upgrading to 4.0](upgrade-4.md))
- **Testing**: all stable releases are manually tested before tagging

## Rolling back to a stable version

If you encounter bugs in a newer version:

**Option 1: the quick installer (recommended)**

Close CODESYS, clear a branch selection and run the installer from `main`; its
menu lists the stable releases and installs the one chosen:

```powershell
Remove-Item Env:CTS_BRANCH -ErrorAction SilentlyContinue
irm https://raw.githubusercontent.com/ArthurkaX/cds-text-sync/main/irm/setup.ps1 | iex
```

**Option 2: a Git clone of the program**

Check out the release tag (`git tag` lists them, e.g. `git checkout v3.4.1`),
then follow the installation steps of that version's own `docs/install.md`:
older releases install differently from the current one.

> [!NOTE]
> Always back up your project before rolling back to a different version.
