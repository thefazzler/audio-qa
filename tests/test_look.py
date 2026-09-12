"""Appearance: palettes, text size, contrast and motion. See D38.

Everything here is a pure mapping from a saved look to Streamlit theme
options, plus the arithmetic that says whether a palette can be read. The
rendering is not tested, for the reason test_web_shell.py gives; what is
tested is that every option the module emits is real, that the default look
emits nothing, that every palette clears WCAG AA and the overlay clears AAA,
and that the setting round-trips through the settings file.
"""

from __future__ import annotations

import pytest

from qa.web import look
from qa.web.look import (
    DEFAULT_PALETTE,
    DEFAULT_TEXT_SIZE,
    HIGH_CONTRAST_DARK,
    HIGH_CONTRAST_LIGHT,
    MANAGED_KEYS,
    PALETTES,
    TEXT_SIZES,
    Look,
    contrast,
    css,
    flags,
    theme_options,
)

AA = 4.5
AAA = 7.0
UI = 3.0  # non-text contrast, for a control against its background


# ---------------------------------------------------------------------------
# The options are real, and the default look sends nothing
# ---------------------------------------------------------------------------

def test_every_managed_key_is_a_real_streamlit_theme_option():
    """A key Streamlit dropped would make qa-web refuse to start, elsewhere."""
    streamlit_config = pytest.importorskip("streamlit.config")
    known = streamlit_config._config_options_template
    unknown = [k for k in MANAGED_KEYS if k not in known]
    assert not unknown, f"streamlit no longer has: {', '.join(unknown)}"


def test_the_default_look_changes_nothing():
    """A machine that never opened Appearance must render exactly as before."""
    assert Look().is_default()
    assert all(v is None for v in theme_options(Look()).values())
    assert flags({}) == []
    assert css(Look()) == ""


def test_every_option_emitted_is_a_managed_key():
    for palette in PALETTES:
        for hc in (False, True):
            emitted = theme_options(Look(palette=palette.key, high_contrast=hc))
            assert set(emitted) == set(MANAGED_KEYS)


def test_flags_come_in_pairs_and_name_real_options():
    streamlit_config = pytest.importorskip("streamlit.config")
    known = streamlit_config._config_options_template
    out = flags({"theme": "ocean", "text_size": "large", "high_contrast": True})
    assert len(out) % 2 == 0
    keys = [f[2:] for f in out[::2]]
    assert all(f.startswith("--theme.") for f in out[::2])
    assert all(k in known for k in keys)
    assert not any(v.startswith("--") for v in out[1::2])
    # Booleans reach the command line as Streamlit spells them.
    assert "true" in out[1::2] and "True" not in out[1::2]


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

def test_the_three_asked_for_are_there_and_light_is_first():
    keys = [p.key for p in PALETTES]
    assert keys[0] == DEFAULT_PALETTE == "light"
    assert "dark" in keys
    assert "lights_out" in keys
    assert len(PALETTES) >= 6, "a choice of palettes, not just a switch"


def test_lights_out_is_actually_black():
    lights_out = look.PALETTE_BY_KEY["lights_out"]
    assert lights_out.background == "#000000"
    assert lights_out.base == "dark"


@pytest.mark.parametrize("palette", PALETTES, ids=lambda p: p.key)
def test_every_palette_is_readable(palette):
    """Body text at AA against both backgrounds, sidebar included."""
    assert contrast(palette.text, palette.background) >= AA, palette.key
    assert contrast(palette.text, palette.secondary) >= AA, palette.key
    sidebar_text = palette.sidebar_text or palette.text
    sidebar_bg = palette.sidebar_background or palette.background
    assert contrast(sidebar_text, sidebar_bg) >= AA, f"{palette.key} sidebar"
    assert contrast(palette.primary, palette.background) >= UI, f"{palette.key} primary"


def test_choosing_light_on_purpose_is_the_same_as_never_choosing():
    """Light is Streamlit's own; sending it would be saying the default aloud."""
    assert all(v is None for v in theme_options(Look(palette="light")).values())


@pytest.mark.parametrize(
    "palette", [p for p in PALETTES if p.key != "light"], ids=lambda p: p.key
)
def test_a_palette_sets_its_base_and_its_colours(palette):
    options = theme_options(Look(palette=palette.key))
    assert options["theme.base"] == palette.base
    assert options["theme.backgroundColor"] == palette.background
    assert options["theme.textColor"] == palette.text
    # Regular text size is Streamlit's own, so it is not sent.
    assert options["theme.baseFontSize"] is None
    assert options["theme.showWidgetBorder"] is None


def test_a_dark_palette_is_dark_and_a_light_one_is_light():
    """`base` decides what Streamlit derives; it must agree with the colours."""
    for palette in PALETTES:
        dark = look.luminance(palette.background) < 0.2
        assert (palette.base == "dark") == dark, palette.key


# ---------------------------------------------------------------------------
# High contrast
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("overlay", [HIGH_CONTRAST_LIGHT, HIGH_CONTRAST_DARK], ids=["light", "dark"])
def test_the_overlay_is_aaa_everywhere_it_puts_text(overlay):
    bg = overlay["theme.backgroundColor"]
    assert contrast(overlay["theme.textColor"], bg) >= AAA
    assert contrast(overlay["theme.textColor"], overlay["theme.secondaryBackgroundColor"]) >= AAA
    assert contrast(overlay["theme.linkColor"], bg) >= AAA
    assert contrast(overlay["theme.sidebar.textColor"], overlay["theme.sidebar.backgroundColor"]) >= AAA
    # White button text on the primary colour, which the default red fails.
    assert contrast("#ffffff", overlay["theme.primaryColor"]) >= AA
    assert contrast(overlay["theme.borderColor"], bg) >= AAA


def test_high_contrast_is_black_on_white_or_white_on_black():
    light = theme_options(Look(palette="aubergine", high_contrast=True))
    assert (light["theme.textColor"], light["theme.backgroundColor"]) == ("#000000", "#ffffff")
    dark = theme_options(Look(palette="ocean", high_contrast=True))
    assert (dark["theme.textColor"], dark["theme.backgroundColor"]) == ("#ffffff", "#000000")


def test_high_contrast_adds_borders_underlines_and_weight():
    options = theme_options(Look(high_contrast=True))
    assert options["theme.showWidgetBorder"] is True
    assert options["theme.linkUnderline"] is True
    assert options["theme.baseFontWeight"] == 500
    assert "focus-visible" in css(Look(high_contrast=True))


def test_high_contrast_follows_the_palette_it_is_laid_over():
    """Dark stays dark under the overlay; nobody asked for a flashbang."""
    assert theme_options(Look(palette="lights_out", high_contrast=True))["theme.base"] == "dark"
    assert theme_options(Look(palette="solarized", high_contrast=True))["theme.base"] == "light"


# ---------------------------------------------------------------------------
# Text size and motion
# ---------------------------------------------------------------------------

def test_regular_is_streamlits_own_size_and_the_others_are_larger():
    sizes = [px for _, px in TEXT_SIZES.values()]
    assert TEXT_SIZES[DEFAULT_TEXT_SIZE][1] == 16
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)
    assert sizes[-1] >= 20, "extra large has to be noticeably larger"


def test_a_larger_text_size_is_sent_as_the_base_font_size():
    assert theme_options(Look(text_size="extra_large"))["theme.baseFontSize"] == TEXT_SIZES["extra_large"][1]
    assert "--theme.baseFontSize" in flags({"text_size": "large"})


def test_reduce_motion_is_a_stylesheet_and_nothing_else():
    sheet = css(Look(reduce_motion=True))
    assert "animation-duration" in sheet and "transition-duration" in sheet
    assert all(v is None for v in theme_options(Look(reduce_motion=True)).values())


# ---------------------------------------------------------------------------
# What the machine remembers
# ---------------------------------------------------------------------------

@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr("qa.library.config_path", lambda: tmp_path / "config.json")
    return tmp_path


def test_a_look_round_trips_through_the_settings_file(profile):
    wanted = Look(palette="forest", text_size="large", high_contrast=True, reduce_motion=True)
    look.save(wanted)
    assert look.current() == wanted


def test_saving_a_look_does_not_disturb_the_other_settings(profile):
    from qa.library import read_settings, set_output

    set_output(profile / "packets")
    look.save(Look(palette="dark"))
    assert "output" in read_settings()
    assert read_settings()["theme"] == "dark"


def test_a_stale_or_hand_edited_setting_falls_back_rather_than_failing():
    got = Look.from_settings({"theme": "no-such-palette", "text_size": 99, "high_contrast": "yes"})
    assert got.palette == DEFAULT_PALETTE
    assert got.text_size == DEFAULT_TEXT_SIZE
    assert got.high_contrast is True


def test_a_fresh_machine_has_the_default_look(profile):
    assert look.current() == Look()


def test_the_contrast_arithmetic_is_the_wcag_one():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
