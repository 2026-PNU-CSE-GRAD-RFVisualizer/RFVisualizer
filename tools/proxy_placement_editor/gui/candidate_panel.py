"""Candidate template picker."""


class CandidatePanel:
    def __init__(self, core, on_add):
        from open3d.visualization import gui

        self.widget = gui.CollapsableVert(
            "Candidate Library", 0.25, gui.Margins(6, 6, 6, 6)
        )
        self.combo = gui.Combobox()
        for value in core.candidates:
            self.combo.add_item("{} — placeholder".format(value.label))
        button = gui.Button("Add disabled provisional object")
        button.set_on_clicked(
            lambda: on_add(core.candidates[self.combo.selected_index].id)
        )
        self.widget.add_child(self.combo)
        self.widget.add_child(button)
