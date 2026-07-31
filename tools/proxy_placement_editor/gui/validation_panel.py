"""Compact real-time validation and external command log."""

import textwrap

from .strings_ko import localize_message, status_label, tr
from .section import make_section

LOG_WRAP_COLUMNS = 42
MAX_LOG_LINES = 10


def wrap_log_lines(value, width=LOG_WRAP_COLUMNS):
    """Wrap long paths and command output before Open3D lays out the sidebar."""
    lines = []
    for line in str(value).splitlines() or [""]:
        lines.extend(
            textwrap.wrap(
                line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


class ValidationPanel:
    def __init__(self, heading_font_id=None, ui_scale=1.0):
        from open3d.visualization import gui

        self.widget = make_section(
            gui, tr("validation"), heading_font_id, ui_scale
        )
        self.summary = gui.Label(tr("not_validated"))
        self.summary.text_color = gui.Color(1.0, 0.75, 0.1)
        self.log = gui.ListView()
        self.log.set_max_visible_items(5)
        self._log_lines = []
        self.widget.add_child(self.summary)
        self.widget.add_child(self.log)

    def refresh(self, report, selected):
        text = tr("validation_pass") if report["success"] else tr("validation_error")
        if selected:
            record = next(
                (value for value in report["objects"] if value["id"] == selected), None
            )
            if record:
                text += " | {}: {}".format(selected, status_label(record["status"]))
                if record.get("renderable") and record.get("object_kind") != "rx":
                    c = record["phase2b_validation"]["containment"]
                    text += (
                        "\n{} {:.4f} m | {} {:.4f} m | {} {:.4f} m".format(
                            tr("floor"),
                            c["minimum_floor_clearance_m"],
                            tr("ceiling"),
                            c["minimum_ceiling_clearance_m"],
                            tr("wall"),
                            c["minimum_wall_clearance_m"],
                        )
                    )
                elif record.get("object_kind") == "rx":
                    position = record.get("source", {}).get("position_m", [])
                    if len(position) == 3:
                        text += "\n위치 X {:.3f} | Y {:.3f} | Z {:.3f} m".format(
                            *position
                        )
                if record["errors"]:
                    text += "\n" + "\n".join(
                        localize_message(value) for value in record["errors"][:3]
                    )
                if record["warnings"]:
                    text += "\n" + "\n".join(
                        localize_message(value) for value in record["warnings"][:3]
                    )
        self.summary.text = text

    def append_log(self, line):
        self._log_lines = (
            self._log_lines + wrap_log_lines(localize_message(line))
        )[-MAX_LOG_LINES:]
        self.log.set_items(self._log_lines)
        self.log.selected_index = len(self._log_lines) - 1
