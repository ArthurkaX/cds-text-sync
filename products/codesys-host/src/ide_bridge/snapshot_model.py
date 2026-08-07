"""Pure snapshot document normalization helpers."""


def vars_key(data):
    if isinstance(data, dict) and "variables" in data:
        return "variables"
    return "vars"


def vars_from_data(data):
    if isinstance(data, dict):
        return list(data.get("variables", data.get("vars", [])))
    return list(data or [])


def make_document(variables, format_version, created, project_name="",
                  app="Application", label="", description=""):
    return {
        "meta": {
            "format_version": format_version,
            "created": created,
            "project": project_name or "",
            "app": "" if app is None else str(app),
            "label": "" if label is None else str(label),
            "description": "" if description is None else str(description),
        },
        "variables": variables,
    }
