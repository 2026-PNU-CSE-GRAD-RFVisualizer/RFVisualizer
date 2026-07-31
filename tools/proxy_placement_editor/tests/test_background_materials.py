from types import SimpleNamespace

import pytest

from tools.proxy_placement_editor.gui.viewport import (
    GIZMO_RENDER_PRIORITY,
    PlacementViewport,
    background_mesh_material_spec,
)


class FakeMaterialRecord:
    def __init__(self):
        self.shader = ""
        self.has_alpha = False
        self.base_color = [0.0, 0.0, 0.0, 0.0]


@pytest.mark.parametrize(
    "layer_name,expected_color",
    (
        ("proxy_mesh", (0.82, 0.88, 0.98)),
        ("pgsr_output_mesh", (1.0, 1.0, 1.0)),
    ),
)
def test_background_mesh_materials_are_opaque_and_unlit(
    layer_name, expected_color
):
    spec = background_mesh_material_spec(layer_name)
    viewport = PlacementViewport.__new__(PlacementViewport)
    viewport.rendering = SimpleNamespace(MaterialRecord=FakeMaterialRecord)

    material = viewport._material(**spec)

    assert material.shader == "defaultUnlit"
    assert material.has_alpha is False
    assert material.base_color == [*expected_color, 1.0]


def test_unknown_background_mesh_material_is_rejected():
    with pytest.raises(ValueError, match="알 수 없는"):
        background_mesh_material_spec("unknown")


def test_existing_transparent_obstacle_material_path_is_unchanged():
    viewport = PlacementViewport.__new__(PlacementViewport)
    viewport.rendering = SimpleNamespace(MaterialRecord=FakeMaterialRecord)

    material = viewport._material((0.5, 0.4, 0.3), alpha=0.5)

    assert material.shader == "defaultLitTransparency"
    assert material.has_alpha is True
    assert material.base_color == [0.5, 0.4, 0.3, 0.5]


def test_gizmo_geometry_is_added_with_always_on_top_priority():
    class FakeLowLevelScene:
        def __init__(self):
            self.priorities = []

        def set_geometry_priority(self, name, priority):
            self.priorities.append((name, priority))

    class FakeScene:
        def __init__(self):
            self.scene = FakeLowLevelScene()
            self.added = []

        def add_geometry(self, name, geometry, material):
            self.added.append((name, geometry, material))

    viewport = PlacementViewport.__new__(PlacementViewport)
    viewport.widget = SimpleNamespace(scene=FakeScene())
    viewport._gizmo_geometry_names = set()

    viewport._add_gizmo_geometry("gizmo::axis", "geometry", "material")

    assert viewport.widget.scene.added == [
        ("gizmo::axis", "geometry", "material")
    ]
    assert viewport.widget.scene.scene.priorities == [
        ("gizmo::axis", GIZMO_RENDER_PRIORITY)
    ]
    assert viewport._gizmo_geometry_names == {"gizmo::axis"}

