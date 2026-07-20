"""Compact real-time validation and external command log."""

from .strings_ko import localize_message, status_label, tr
from .section import make_section


class ValidationPanel:
    def __init__(self, heading_font_id=None):
        from open3d.visualization import gui

        self.widget = make_section(gui, tr("validation"), heading_font_id)
        self.summary = gui.Label(tr("not_validated"))
        self.summary.text_color = gui.Color(1.0, 0.75, 0.1)
        self.log = gui.Label("")
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
                if record.get("renderable"):
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
        values = (self.log.text + "\n" + line).strip().splitlines()[-10:]
        self.log.text = "\n".join(values)
