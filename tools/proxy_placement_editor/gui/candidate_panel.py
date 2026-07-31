"""Candidate template picker."""

from .strings_ko import candidate_label, tr
from .metrics import scaled
from .section import make_section


class CandidatePanel:
    def __init__(
        self, core, on_add, on_add_receiver, heading_font_id=None, ui_scale=1.0
    ):
        from open3d.visualization import gui

        self.widget = make_section(
            gui, tr("candidate_library"), heading_font_id, ui_scale
        )
        self.combo = gui.Combobox()
        for value in core.candidates:
            self.combo.add_item(
                "{} — {}".format(
                    candidate_label(value.id, value.label),
                    tr("candidate_placeholder"),
                )
            )
        button = gui.Button(tr("add_candidate"))
        button.set_on_clicked(
            lambda: on_add(core.candidates[self.combo.selected_index].id)
        )
        marker_actions = gui.Horiz(scaled(4, ui_scale))
        calibration = gui.Button(tr("add_calibration_rx"))
        test = gui.Button(tr("add_test_rx"))
        calibration.set_on_clicked(lambda: on_add_receiver("calibration"))
        test.set_on_clicked(lambda: on_add_receiver("test"))
        marker_actions.add_child(calibration)
        marker_actions.add_child(test)
        self.widget.add_child(self.combo)
        self.widget.add_child(button)
        self.widget.add_child(marker_actions)
