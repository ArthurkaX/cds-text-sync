"""
workspace.py - Locating the sync folder and its project-view.

``cts analyze`` works only on the exported ``project-view/`` tree. It never
talks to the daemon and never reads ``.dump/``.

Resolution priority:

1. ``--workspace`` (explicit);
2. the nearest ancestor directory that contains both ``cts-analyze.toml``
   and ``project-view/``;
3. an explicit ``--project-view`` directory;
4. a clear error (no daemon lookup).
"""

from __future__ import annotations

import os

CONFIG_FILENAME = "cts-analyze.toml"
PROJECT_VIEW_DIRNAME = "project-view"
STATE_DIRNAME = ".cts-analyze"


class WorkspaceError(Exception):
    """The workspace could not be located or is malformed."""


class Workspace:
    """Strictly defined paths of one analysis workspace."""

    def __init__(self, root, project_view, state_dir, config_path=None):
        self.root = root  # sync folder
        self.project_view = project_view
        self.state_dir = state_dir
        self.config_path = config_path

    def __repr__(self):
        return f"<Workspace root={self.root} project_view={self.project_view}>"


class WorkspaceResolver:
    """Resolve a Workspace from CLI options and the filesystem."""

    def __init__(self, workspace=None, project_view=None, cwd=None):
        self.explicit_workspace = workspace or ""
        self.explicit_project_view = project_view or ""
        self.cwd = cwd or os.getcwd()

    def resolve(self):
        explicit = self.explicit_workspace.strip()
        explicit_pv = self.explicit_project_view.strip()

        if explicit and explicit_pv:
            raise WorkspaceError("Pass either --workspace or --project-view, not both.")

        # 3. Explicit project-view directory.
        if explicit_pv:
            pv = os.path.abspath(explicit_pv)
            if not os.path.isdir(pv):
                raise WorkspaceError(f"project-view directory not found: {pv}")
            root = os.path.dirname(pv)
            config = self._find_config(root, pv)
            return Workspace(
                root=root,
                project_view=pv,
                state_dir=os.path.join(root, STATE_DIRNAME),
                config_path=config,
            )

        # 1. Explicit --workspace (a sync folder, or a project-view dir
        #    passed directly).
        if explicit:
            base = os.path.abspath(explicit)
            if not os.path.isdir(base):
                raise WorkspaceError(f"workspace directory not found: {base}")
            if os.path.basename(base) == PROJECT_VIEW_DIRNAME:
                config = self._find_config(os.path.dirname(base), base)
                return Workspace(
                    root=os.path.dirname(base),
                    project_view=base,
                    state_dir=os.path.join(os.path.dirname(base), STATE_DIRNAME),
                    config_path=config,
                )
            return self._from_base(base)

        # 2. Nearest ancestor with config + project-view.
        config = self._find_config(self.cwd, None)
        if config is not None:
            base = os.path.dirname(config)
            pv = os.path.join(base, PROJECT_VIEW_DIRNAME)
            if os.path.isdir(pv):
                return self._from_base(base)

        # 3 (retry). project-view in cwd or an ancestor.
        pv = self._find_project_view(self.cwd)
        if pv is not None:
            root = os.path.dirname(pv)
            config = self._find_config(root, pv)
            return Workspace(
                root=root,
                project_view=pv,
                state_dir=os.path.join(root, STATE_DIRNAME),
                config_path=config,
            )

        raise WorkspaceError(
            "No analysis workspace found. Pass --workspace <sync-folder> or "
            "--project-view <dir>, or run from a folder that contains a "
            "project-view/ directory (optionally with a cts-analyze.toml)."
        )

    def _from_base(self, base):
        pv = os.path.join(base, PROJECT_VIEW_DIRNAME)
        if not os.path.isdir(pv):
            raise WorkspaceError(f"project-view not found under workspace: {pv}")
        config = self._find_config(base, pv)
        return Workspace(
            root=base,
            project_view=pv,
            state_dir=os.path.join(base, STATE_DIRNAME),
            config_path=config,
        )

    @staticmethod
    def _find_config(base, pv):
        """A config next to the sync folder (or beside project-view)."""
        if base and os.path.isfile(os.path.join(base, CONFIG_FILENAME)):
            return os.path.join(base, CONFIG_FILENAME)
        if pv and os.path.isfile(os.path.join(pv, CONFIG_FILENAME)):
            return os.path.join(pv, CONFIG_FILENAME)
        return None

    @staticmethod
    def _find_project_view(start):
        current = os.path.abspath(start)
        while True:
            pv = os.path.join(current, PROJECT_VIEW_DIRNAME)
            if os.path.isdir(pv):
                return pv
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent
