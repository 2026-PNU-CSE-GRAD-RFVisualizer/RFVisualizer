"""Consistent large sidebar section headings and dividers."""


def make_section(gui, title, heading_font_id=None):
    section = gui.Vert(5, gui.Margins(6, 10, 6, 6))
    heading = gui.Label(title)
    if heading_font_id is not None:
        heading.font_id = int(heading_font_id)
    heading.text_color = gui.Color(0.92, 0.95, 1.0)
    # A colored layout avoids font-dependent box-drawing glyphs turning into
    # question marks in Open3D's limited fallback atlas.
    divider = gui.Vert(0)
    divider.background_color = gui.Color(0.28, 0.34, 0.43)
    divider.add_fixed(2)
    section.add_child(heading)
    section.add_child(divider)
    return section
