# Development Workflow

This document explains the recommended team workflow for PLC development using **cds-text-sync**.

## Overview

The workflow is designed to combine the robustness of CODESYS for hardware configuration and HMI development with Git-based review of the XML-first exported view tree.

![Development Workflow](../img/Workflow.svg)

The steps below use the CODESYS-side `Project_*.py` entrypoints. The same
export / compare / import / build actions can also be driven from a shell with
the `cts` CLI once `Project_daemon.py` is running inside CODESYS (see
[`cds_text_sync/CLI.md`](../products/cds-text-sync/src/cds_text_sync/CLI.md)).

## 1. Project Initialization

Before the team can start working, the project must be prepared:

1.  **Set the project folder**: Run `Project_directory.py` and select the sync folder for the open project. The default profile exports all supported `.st` and `.csv` text projections.
2.  **Choose advanced options if needed**: Run `Project_options.py` on the **empty** sync folder only when you need to change XML-first/text-first mode, layout, profile, or text-export selection. The mode is fixed once the first export runs; switching later requires a new empty sync folder.
3.  **Extract Project**: The initial state of the CODESYS project is exported using `Project_export.py`. This writes the current native snapshot to `.dump/IDE.xml` and refreshes the editable `project-view/` tree for review.
4.  **Choose Git Scope**: For team review, track `project-view/` intentionally and ignore volatile `.dump` files such as snapshots, reports, and generated patches.
5.  **Initialize Repository**: A Git repository is created, and the chosen exported view files (and optionally the `.project` binary using LFS) are pushed to a remote server (e.g., GitHub, GitLab).

### Text-first projects: what is tracked

In text-first mode the tracked surface is intentionally text:

- **Tracked**: `project-view/**/*.st` (and `.csv` projections), the native `.xml` of kinds kept in the view via `xml_in_view_kinds` (default: visualizations), and `cds-text-sync.json`.
- **Not tracked**: everything in `.dump/`, including the tool-owned `.dump/xml/` structural mirror. A teammate's fresh clone has no `.dump/` at all — `Project_import.py` still applies the `.st` files by overlaying them on a fresh IDE baseline, and objects missing from the IDE are recreated from their text.
- Local `.st` edits are protected: export skips (or, interactively, asks before overwriting) any file changed on disk that has not been imported yet.

## 2. Team Roles

### 🔧 HMI / Hardware Engineer (Main Branch Owner)

- **Role**: Acts as the gatekeeper of the project.
- **Responsibilities**:
  - Maintains the integrity of the Hardware Configuration and HMI.
  - Manages the `main` branch.
  - Reviews incoming Pull Requests from developers.
  - Ensures that merged logic is compatible with the physical hardware.

### 👨‍💻 Development Team (Engineers)

- **Role**: Implement features and fix bugs.
- **Responsibilities**:
  - Clone the project to their local machines.
  - Develop logic using external editors or CODESYS.
  - Sync changes and submit them for review via Pull Requests.

## 3. The Development Cycle

For every new task (Feature or Bug Fix), developers follow these steps:

1.  **Clone / Sync**: Clone the repository or `git pull` the latest changes from `main`.
2.  **Make Changes**: Open the CODESYS project and implement the required logic.
3.  **Extract to Disk**: Run `Project_export.py` to update `project-view/` with the latest CODESYS state before committing.
4.  **Compare When Needed**: Run `Project_compare_ui.py` before committing to see what differs as a CODESYS dialog with full import/export actions; it also writes the machine-readable `.dump/compare_report.json`. From a shell or in CI, `cts compare` gives the same report without a dialog.
5.  **Commit & Push**: Use Git to commit the updated view files and push them to a dedicated **feature branch**.
6.  **Create Pull Request**: Open a Pull Request (PR) to merge the feature branch into `main`.

## 4. Code Review & Integration

1.  **Review**: The Main Branch Owner reviews the code changes.
2.  **Approval**:
    - **Yes**: If the code is correct and follows standards, it is merged into `main`.
    - **No**: If revisions are needed, feedback is provided, and the developer returns to the "Make Changes" step in the development cycle.
3.  **Team Sync**: Once merged, all other team members can pull the updated `main` branch into their local environments.
