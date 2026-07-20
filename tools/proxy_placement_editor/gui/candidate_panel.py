"""Candidate template picker."""

from .strings_ko import candidate_label, tr
from .section import make_section


class CandidatePanel:
    def __init__(self, core, on_add, heading_font_id=None):
        from open3d.visualization import gui

        self.widget = make_section(gui, tr("candidate_library"), heading_font_id)
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
        self.widget.add_child(self.combo)
        self.widget.add_child(button)
