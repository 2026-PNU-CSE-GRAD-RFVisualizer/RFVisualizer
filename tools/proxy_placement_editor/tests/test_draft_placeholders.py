def test_null_draft_objects_get_visible_disabled_placeholders(draft_core):
    changed = draft_core.materialize_draft_placeholders()
    assert changed == [
        "desk_block_example",
        "blackboard_example",
        "door_example",
        "large_metal_object_example",
    ]
    report = draft_core.validate()
    assert report["renderable_obstacle_count"] == 4
    assert report["enabled_obstacle_count"] == 0
    assert all(value["renderable"] for value in report["objects"])
    assert all(not value["enabled"] for value in report["objects"])
    assert all(
        value["source"]["placement_status"] == "provisional_placeholder"
        for value in report["objects"]
    )


def test_materializing_draft_placeholders_is_idempotent(draft_core):
    assert draft_core.materialize_draft_placeholders()
    assert draft_core.materialize_draft_placeholders() == []
