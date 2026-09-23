"""build_command: argv assembly from node parameters.

Covers the fixed argument order, :g float formatting for --seconds, and that
optional arguments appear iff their input is set.
"""

BASE = dict(
    binary="/opt/h3.c/h3",
    model_dir="/models/MiniMax-H3",
    prompt="a cat walking through neon rain",
    width=864,
    height=480,
    seconds=2.0,
    steps=20,
    layers=45,
    reuse=2,
    seed=42,
    output_path="/tmp/out.mp4",
)


def cmd(runner, **over):
    kw = dict(BASE)
    kw.update(over)
    return runner.build_command(**kw)


def test_minimal_command_exact_argv(runner):
    assert cmd(runner) == [
        "/opt/h3.c/h3", "--profile",
        "-d", "/models/MiniMax-H3",
        "-p", "a cat walking through neon rain",
        "--width", "864",
        "--height", "480",
        "--seconds", "2",
        "--steps", "20",
        "--layers", "45",
        "--reuse", "2",
        "--seed", "42",
        "-o", "/tmp/out.mp4",
    ]


def test_optional_args_absent_by_default(runner):
    argv = cmd(runner)
    for flag in (
        "--first-frame", "--last-frame", "--ref-image", "--ref-image-size",
        "--ref-audio", "--token-reduction", "--ssd-streaming",
    ):
        assert flag not in argv


def test_seconds_g_formatting(runner):
    assert "--seconds" in cmd(runner, seconds=2.5)
    argv = cmd(runner, seconds=2.5)
    assert argv[argv.index("--seconds") + 1] == "2.5"
    argv = cmd(runner, seconds=0.25)
    assert argv[argv.index("--seconds") + 1] == "0.25"
    argv = cmd(runner, seconds=3.0)
    assert argv[argv.index("--seconds") + 1] == "3"


def test_full_64bit_seed_passed_verbatim(runner):
    argv = cmd(runner, seed=2**64 - 1)
    assert argv[argv.index("--seed") + 1] == str(2**64 - 1)


def test_first_and_last_frame(runner):
    argv = cmd(runner, first_frame="/tmp/f.png", last_frame="/tmp/l.png")
    assert argv[argv.index("--first-frame") + 1] == "/tmp/f.png"
    assert argv[argv.index("--last-frame") + 1] == "/tmp/l.png"


def test_each_ref_image_gets_its_own_flag(runner):
    argv = cmd(runner, ref_images=["/tmp/r0.png", "/tmp/r1.png", "/tmp/r2.png"])
    positions = [i for i, v in enumerate(argv) if v == "--ref-image"]
    assert [argv[i + 1] for i in positions] == ["/tmp/r0.png", "/tmp/r1.png", "/tmp/r2.png"]


def test_ref_image_size_only_with_ref_images(runner):
    argv = cmd(runner, ref_images=["/tmp/r0.png"], ref_image_size="max")
    assert argv[argv.index("--ref-image-size") + 1] == "max"
    # ref_image_size is ignored when there are no reference images
    argv = cmd(runner, ref_image_size="max")
    assert "--ref-image-size" not in argv


def test_ref_audio(runner):
    argv = cmd(runner, ref_audio="/tmp/a.wav")
    assert argv[argv.index("--ref-audio") + 1] == "/tmp/a.wav"


def test_speed_flags_appended_at_end(runner):
    argv = cmd(runner, token_reduction=True, ssd_streaming=True)
    assert argv[-2:] == ["--token-reduction", "--ssd-streaming"]


def test_everything_combined(runner):
    argv = cmd(
        runner,
        first_frame="/tmp/f.png",
        ref_images=["/tmp/r0.png"],
        ref_image_size="match",
        ref_audio="/tmp/a.wav",
        token_reduction=True,
    )
    for flag in ("--first-frame", "--ref-image", "--ref-image-size",
                 "--ref-audio", "--token-reduction"):
        assert flag in argv
    assert "--last-frame" not in argv
    assert "--ssd-streaming" not in argv
