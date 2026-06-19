"""
ui/file_actions.py — Shared file-operation helpers for all DocuWise document lists.

Every panel that shows document rows imports from here so open/folder/copy
behaviour is consistent across: document table, duplicates panel, image panel,
missing-files panel, and any future list.
"""

from __future__ import annotations

import os
import subprocess

from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import QMenu, QMessageBox, QWidget


# ---------------------------------------------------------------------------
# Core actions
# ---------------------------------------------------------------------------

def open_document(file_path: str, parent: QWidget | None = None) -> None:
    """
    Open *file_path* with the system default application.

    If the file no longer exists on disk, show a clear warning dialog and
    do nothing else (Feature 7 — file exists guard).
    """
    if not file_path:
        return
    if not os.path.exists(file_path):
        QMessageBox.warning(
            parent,
            "File Not Found",
            "File no longer exists at the stored location.\n\n"
            f"Path: {file_path}",
        )
        return
    try:
        os.startfile(file_path)                          # Windows
    except AttributeError:
        subprocess.Popen(["xdg-open", file_path])        # Linux fallback
    except Exception as exc:
        QMessageBox.warning(parent, "Open Error", f"Could not open file:\n{exc}")


def open_containing_folder(file_path: str, parent: QWidget | None = None) -> None:
    """
    Open the containing folder in Windows Explorer and select the file.
    Falls back to opening just the folder if the file is missing.
    """
    if not file_path:
        return
    norm = os.path.normpath(file_path)
    if os.path.exists(norm):
        try:
            subprocess.Popen(["explorer", "/select,", norm])
            return
        except Exception:
            pass
    # File missing — just open the parent folder
    folder = os.path.dirname(norm)
    if os.path.isdir(folder):
        try:
            subprocess.Popen(["explorer", folder])
        except Exception as exc:
            QMessageBox.warning(parent, "Open Error", f"Could not open folder:\n{exc}")
    else:
        QMessageBox.warning(
            parent, "Folder Not Found",
            f"The containing folder no longer exists:\n{folder}",
        )


def copy_file_path(file_path: str) -> None:
    """Copy the absolute file path to the system clipboard."""
    if file_path:
        QGuiApplication.clipboard().setText(file_path)


# ---------------------------------------------------------------------------
# Context menu factory (Feature 6)
# ---------------------------------------------------------------------------

def make_context_menu(
    file_path: str,
    parent: QWidget | None = None,
    extra_actions: list[QAction] | None = None,
) -> QMenu:
    """
    Build a standard right-click context menu for any document row.

    Standard items:
      - Open File
      - Open Containing Folder
      - Copy File Path
      - (separator)
      - any *extra_actions* provided by the caller

    Args:
        file_path:     Absolute path of the document row.
        parent:        Parent widget for dialogs and menu ownership.
        extra_actions: Optional additional QActions to append after separator.

    Returns:
        A populated QMenu ready to call .exec() on.
    """
    menu = QMenu(parent)

    act_open = QAction("Open File", menu)
    act_open.triggered.connect(lambda: open_document(file_path, parent))
    menu.addAction(act_open)

    act_folder = QAction("Open Containing Folder", menu)
    act_folder.triggered.connect(lambda: open_containing_folder(file_path, parent))
    menu.addAction(act_folder)

    act_copy = QAction("Copy File Path", menu)
    act_copy.triggered.connect(lambda: copy_file_path(file_path))
    menu.addAction(act_copy)

    if extra_actions:
        menu.addSeparator()
        for action in extra_actions:
            menu.addAction(action)

    return menu
