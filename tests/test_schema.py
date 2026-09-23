"""Schema / loading tests: import the plugin like ComfyUI would and inspect
the V3 node schemas.

These need a ComfyUI checkout (comfy_api, comfy, folder_paths) on sys.path;
conftest.load_plugin_package uses COMFYUI_ROOT or its built-in default and
skips if no checkout is found.
"""

import asyncio

COMMON_INPUTS = {
    "prompt", "width", "height", "seconds", "steps", "preset", "seed",
    "token_reduction", "ssd_streaming", "binary_path", "model_dir",
}


def schemas(plugin):
    ext = asyncio.run(plugin.comfy_entrypoint())
    nodes = asyncio.run(ext.get_node_list())
    return {cls.define_schema().node_id: cls.define_schema() for cls in nodes}


def input_by_id(schema, input_id):
    for inp in schema.inputs:
        if inp.id == input_id:
            return inp
    raise AssertionError(f"input {input_id!r} not found in {schema.node_id}")


def test_plugin_exposes_exactly_two_nodes(plugin):
    assert set(schemas(plugin)) == {"WildH3TextToVideo", "WildH3RefToVideo"}


def test_text_to_video_schema(plugin):
    schema = schemas(plugin)["WildH3TextToVideo"]
    ids = {inp.id for inp in schema.inputs}

    assert COMMON_INPUTS <= ids
    assert {"first_frame", "last_frame"} <= ids
    # first/last-frame anchoring is structurally mutually exclusive with
    # reference conditioning: this node must not accept reference inputs.
    assert "ref_images" not in ids
    assert "ref_audio" not in ids

    assert input_by_id(schema, "first_frame").optional
    assert input_by_id(schema, "last_frame").optional

    assert schema.category == "Wild H3"
    assert schema.display_name
    assert len(schema.outputs) == 1
    assert schema.outputs[0].io_type == "VIDEO"


def test_ref_to_video_schema(plugin):
    schema = schemas(plugin)["WildH3RefToVideo"]
    ids = {inp.id for inp in schema.inputs}

    assert COMMON_INPUTS <= ids
    assert {"ref_images", "ref_audio", "ref_image_size"} <= ids
    # ... and conversely, no first/last-frame anchors on the Ref2VA node.
    assert "first_frame" not in ids
    assert "last_frame" not in ids

    assert input_by_id(schema, "ref_images").optional
    assert input_by_id(schema, "ref_audio").optional
    assert input_by_id(schema, "ref_image_size").options == ["match", "max"]

    assert len(schema.outputs) == 1
    assert schema.outputs[0].io_type == "VIDEO"


def test_common_input_constraints(plugin):
    for schema in schemas(plugin).values():
        width = input_by_id(schema, "width")
        assert (width.min, width.max, width.step) == (32, 1344, 32)

        height = input_by_id(schema, "height")
        assert (height.min, height.max, height.step) == (32, 1344, 32)

        seconds = input_by_id(schema, "seconds")
        assert (seconds.min, seconds.max, seconds.step) == (0.25, 15.0, 0.25)

        steps = input_by_id(schema, "steps")
        assert (steps.min, steps.max) == (2, 1000)

        seed = input_by_id(schema, "seed")
        assert (seed.min, seed.max) == (0, 0xFFFFFFFFFFFFFFFF)

        preset = input_by_id(schema, "preset")
        assert preset.options == ["precise", "balanced", "fast"]
        assert preset.default == "balanced"

        # Path overrides are advanced inputs and default to "use config.json".
        assert input_by_id(schema, "binary_path").advanced
        assert input_by_id(schema, "binary_path").default == ""
        assert input_by_id(schema, "model_dir").advanced


def test_node_classes_have_matching_execute_signatures(plugin):
    from wild_h3c import nodes

    import inspect

    t2v = inspect.signature(nodes.H3TextToVideo.execute).parameters
    for name in COMMON_INPUTS | {"first_frame", "last_frame"}:
        assert name in t2v

    r2v = inspect.signature(nodes.H3RefToVideo.execute).parameters
    for name in COMMON_INPUTS | {"ref_images", "ref_audio", "ref_image_size"}:
        assert name in r2v
    assert "first_frame" not in r2v
