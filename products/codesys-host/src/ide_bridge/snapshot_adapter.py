"""Runtime adapter for snapshot project/IDE operations."""


class SnapshotProjectAdapter(object):
    """Small boundary around CODESYS and online-engine integrations."""

    def __init__(self, project, exporter, online_helpers, runtime):
        self.project = project
        self.exporter = exporter
        self.online_helpers = online_helpers
        self.runtime = runtime

    def children(self):
        try:
            return list(self.project.get_children(True))
        except Exception:
            try:
                return list(self.project.get_children(recursive=True))
            except Exception:
                return []

    def export_selected_snapshot(self, objects, path):
        return self.exporter.export_selected_snapshot(self.project, objects, path)

    def read_variables(self, names):
        return self.online_helpers.read_variables_impl(self.project, names)

    def run_external_engine(self, args, project_root, dump_root):
        return self.runtime.run_external_engine(
            args, project_root=project_root, dump_root=dump_root
        )
