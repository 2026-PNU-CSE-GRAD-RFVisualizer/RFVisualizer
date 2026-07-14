"""Compact real-time validation and external command log."""


class ValidationPanel:
    def __init__(self):
        from open3d.visualization import gui

        self.widget = gui.CollapsableVert("Validation", 0.25, gui.Margins(6, 6, 6, 6))
        self.summary = gui.Label("Not validated")
        self.summary.text_color = gui.Color(1.0, 0.75, 0.1)
        self.log = gui.Label("")
        self.widget.add_child(self.summary)
        self.widget.add_child(self.log)

    def refresh(self, report, selected):
        text = "PASS" if report["success"] else "ERROR"
        if selected:
            record = next(
                (value for value in report["objects"] if value["id"] == selected), None
            )
            if record:
                text += " | {}: {}".format(selected, record["status"])
                if record.get("renderable"):
                    c = record["phase2b_validation"]["containment"]
                    text += (
                        "\nFloor {:.4f} m | Ceiling {:.4f} m | Wall {:.4f} m".format(
                            c["minimum_floor_clearance_m"],
                            c["minimum_ceiling_clearance_m"],
                            c["minimum_wall_clearance_m"],
                        )
                    )
                if record["errors"]:
                    text += "\n" + "\n".join(record["errors"][:3])
                if record["warnings"]:
                    text += "\n" + "\n".join(record["warnings"][:3])
        self.summary.text = text

    def append_log(self, line):
        values = (self.log.text + "\n" + line).strip().splitlines()[-10:]
        self.log.text = "\n".join(values)
