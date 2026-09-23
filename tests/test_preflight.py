"""Preflight validation rules in h3_runner.preflight / requested_frames.

Every rule gets a positive case (passes) and a negative case (raises with the
rule named in the message). Frame alignment to 5+17n chunks is done inside h3
itself, not by the plugin, so it is intentionally not tested here.
"""

import math

import pytest

OK = dict(
    prompt="a cat walking through neon rain",
    width=864,
    height=480,
    seconds=2.0,
    steps=20,
    seed=42,
    has_refs=False,
    ref_audio_seconds=None,
    n_ref_images=0,
)


def kwargs(**over):
    kw = dict(OK)
    kw.update(over)
    return kw


def fails(runner, **over):
    with pytest.raises(ValueError) as exc_info:
        runner.preflight(**kwargs(**over))
    return str(exc_info.value)


# ---------------------------------------------------------------- baseline


def test_valid_baseline_passes(runner):
    runner.preflight(**kwargs())  # must not raise


def test_empty_prompt_fails(runner):
    assert "prompt is empty" in fails(runner, prompt="")


def test_whitespace_prompt_fails(runner):
    assert "prompt is empty" in fails(runner, prompt="   \n  ")


def test_multiple_violations_are_all_listed(runner):
    msg = fails(runner, width=100, steps=1)
    assert "multiples of 32" in msg
    assert "steps must be 2..1000" in msg
    assert "preflight failed" in msg


# ---------------------------------------------------------------- dimensions


@pytest.mark.parametrize("w,h", [(32, 32), (864, 480), (768, 1344), (1344, 768)])
def test_dimension_positive_cases(runner, w, h):
    runner.preflight(**kwargs(width=w, height=h))


@pytest.mark.parametrize("w,h", [(100, 480), (864, 33), (0, 480), (864, 16), (31, 480)])
def test_non_multiple_or_too_small_fails(runner, w, h):
    assert "multiples of 32" in fails(runner, width=w, height=h)


def test_area_boundary_exactly_max_passes(runner):
    # 768*1344 == MAX_PIXELS
    runner.preflight(**kwargs(width=768, height=1344))


@pytest.mark.parametrize("w,h", [(1024, 1056), (1344, 800)])
def test_area_over_limit_fails(runner, w, h):
    msg = fails(runner, width=w, height=h)
    assert "width*height must be <= 768*1344" in msg
    assert f"{w}x{h}" in msg


# ---------------------------------------------------------------- duration / frames


@pytest.mark.parametrize(
    "seconds,frames",
    [(0.25, 6), (1.0, 24), (2.0, 48), (15.0, 360), (15.08, 362)],
)
def test_requested_frames_matches_llround(runner, seconds, frames):
    assert runner.requested_frames(seconds) == frames


def test_requested_frames_rounds_half_up(runner):
    # 0.4375s * 24 = 10.5 -> llround rounds half away from zero -> 11
    assert runner.requested_frames(0.4375) == 11


@pytest.mark.parametrize("seconds", [0.25, 1.0, 15.0, 15.08])
def test_frame_range_positive_cases(runner, seconds):
    runner.preflight(**kwargs(seconds=seconds))


@pytest.mark.parametrize(
    "seconds",
    [0.2,   # 5 frames, below the 6-frame minimum
     0.0,   # not positive
     -1.0,
     15.2,  # 365 frames, above the 362-frame maximum
     float("nan"),
     float("inf")],
)
def test_frame_range_negative_cases(runner, seconds):
    runner.preflight(**kwargs(seconds=1.0))  # sanity: baseline fine
    msg = fails(runner, seconds=seconds)
    assert "seconds" in msg


def test_frame_error_mentions_frame_count(runner):
    msg = fails(runner, seconds=0.2)
    assert "5 frames" in msg
    assert "6..362" in msg


# ---------------------------------------------------------------- steps


@pytest.mark.parametrize("steps", [2, 20, 1000])
def test_steps_positive(runner, steps):
    runner.preflight(**kwargs(steps=steps))


@pytest.mark.parametrize("steps", [0, 1, 1001, -5])
def test_steps_negative(runner, steps):
    assert "steps must be 2..1000" in fails(runner, steps=steps)


# ---------------------------------------------------------------- seed


@pytest.mark.parametrize("seed", [0, 42, 2**64 - 1])
def test_seed_positive(runner, seed):
    runner.preflight(**kwargs(seed=seed))


@pytest.mark.parametrize("seed", [-1, 2**64])
def test_seed_negative(runner, seed):
    assert "unsigned 64-bit" in fails(runner, seed=seed)


# ---------------------------------------------------------------- references


def test_refs_up_to_9_images_pass(runner):
    runner.preflight(**kwargs(has_refs=True, n_ref_images=9))


def test_refs_over_9_images_fail(runner):
    msg = fails(runner, has_refs=True, n_ref_images=10)
    assert "at most 9 reference images" in msg


@pytest.mark.parametrize("secs", [2.0, 7.5, 15.0])
def test_ref_audio_in_range_passes(runner, secs):
    runner.preflight(**kwargs(has_refs=True, n_ref_images=1, ref_audio_seconds=secs))


@pytest.mark.parametrize("secs", [0.5, 1.99, 15.01, 30.0])
def test_ref_audio_out_of_range_fails(runner, secs):
    msg = fails(runner, has_refs=True, n_ref_images=1, ref_audio_seconds=secs)
    assert "reference audio must be 2..15 seconds" in msg


def test_ref_audio_without_images_fails(runner):
    msg = fails(runner, has_refs=True, n_ref_images=0, ref_audio_seconds=5.0)
    assert "reference audio requires at least one reference image" in msg


def test_no_refs_skips_ref_rules(runner):
    # With has_refs=False the ref limits are not consulted at all.
    runner.preflight(**kwargs(has_refs=False, n_ref_images=99, ref_audio_seconds=None))


# ---------------------------------------------------------------- presets


def test_presets_match_documented_values(runner):
    assert runner.PRESETS == {
        "precise": (50, 1),
        "balanced": (45, 2),
        "fast": (40, 3),
    }
