"""How the interface looks: palette, text size, contrast and motion.

These are settings about the person, not about the tab, so unlike the help
switch in prefs.py they persist in the settings file beside the library
location. Somebody who needs large text needs it at every launch, and making
them ask again each morning would be the tool forgetting the one thing it was
told about them.

**Applied through Streamlit's theme, not through injected CSS.** Every colour
here is a `theme.*` config option, which Streamlit hands to every component it
draws, the data grid included. Injected CSS reaches the page but not the grid,
so a stylesheet dark mode leaves every results table white. The cost is that
the theme is a property of the server rather than of a browser tab: two tabs
of one person's app share it, which on a localhost tool with no login is the
right answer anyway. Motion is the one thing the theme cannot express, so
"reduce motion" is the one stylesheet this module injects.

Two paths apply the same mapping. The launcher passes it as `--theme` flags,
so the first paint is already right. The app applies it again at run time
through the config layer, so a change in the sidebar takes effect on the next
rerun without restarting the server. `theme_options` is the single source
both read; a test holds every key it emits to a real Streamlit option.

Every palette passes a contrast test against WCAG AA for body text, and the
high contrast overlay passes AAA. Those numbers are asserted, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Settings file keys, beside "library", "output" and "tour_seen".
THEME = "theme"
TEXT_SIZE = "text_size"
HIGH_CONTRAST = "high_contrast"
REDUCE_MOTION = "reduce_motion"


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    base: str  # "light" or "dark": what Streamlit derives everything else from
    primary: str
    background: str
    secondary: str
    text: str
    sidebar_background: str | None = None
    sidebar_text: str | None = None
    sidebar_secondary: str | None = None
    border: str | None = None


# Light and Dark are Streamlit's own, spelled out so the contrast test can
# measure them. The rest are the kind of palettes a person picks in Slack or
# in the Mac's appearance settings: a colour they like to sit in all day.
PALETTES: tuple[Palette, ...] = (
    Palette("light", "Light", "light", "#ff4b4b", "#ffffff", "#f0f2f6", "#31333f"),
    Palette("dark", "Dark", "dark", "#ff4b4b", "#0e1117", "#262730", "#fafafa"),
    Palette(
        "lights_out", "Lights out", "dark",
        "#1d9bf0", "#000000", "#16181c", "#e7e9ea",
        sidebar_background="#000000", sidebar_secondary="#16181c", border="#2f3336",
    ),
    Palette(
        "aubergine", "Aubergine", "light",
        "#611f69", "#ffffff", "#f6f3f7", "#1d1c1d",
        sidebar_background="#3f0e40", sidebar_text="#ffffff", sidebar_secondary="#522653",
    ),
    Palette(
        "ocean", "Ocean", "dark",
        "#4cc9f0", "#0b1d2a", "#123449", "#e6f1f7",
        sidebar_background="#081722", sidebar_secondary="#123449",
    ),
    Palette(
        "forest", "Forest", "dark",
        "#7bd389", "#0f1f17", "#1a3328", "#e8f3ec",
        sidebar_background="#0b1811", sidebar_secondary="#1a3328",
    ),
    Palette(
        "solarized", "Solarized", "light",
        "#268bd2", "#fdf6e3", "#eee8d5", "#073642",
        sidebar_background="#eee8d5", sidebar_secondary="#e4ddc6",
    ),
    Palette(
        "graphite", "Graphite", "light",
        "#5e5e63", "#f5f5f7", "#e8e8ed", "#1d1d1f",
        sidebar_background="#ececf1", sidebar_secondary="#dddde3",
    ),
)

PALETTE_BY_KEY = {p.key: p for p in PALETTES}
DEFAULT_PALETTE = "light"

# theme.baseFontSize, in pixels. Regular is Streamlit's own default, so a
# machine that has never touched this setting renders exactly as before.
TEXT_SIZES: dict[str, tuple[str, int]] = {
    "regular": ("Regular", 16),
    "large": ("Large", 18),
    "extra_large": ("Extra large", 21),
}
DEFAULT_TEXT_SIZE = "regular"


@dataclass(frozen=True)
class Look:
    palette: str = DEFAULT_PALETTE
    text_size: str = DEFAULT_TEXT_SIZE
    high_contrast: bool = False
    reduce_motion: bool = False

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "Look":
        """Tolerant of anything: a stale or hand-edited value falls back."""
        palette = settings.get(THEME)
        size = settings.get(TEXT_SIZE)
        return cls(
            palette=palette if palette in PALETTE_BY_KEY else DEFAULT_PALETTE,
            text_size=size if size in TEXT_SIZES else DEFAULT_TEXT_SIZE,
            high_contrast=bool(settings.get(HIGH_CONTRAST, False)),
            reduce_motion=bool(settings.get(REDUCE_MOTION, False)),
        )

    def is_default(self) -> bool:
        return self == Look()

    def themed(self) -> bool:
        """Whether anything here changes Streamlit's own theme.

        Reduce motion is a stylesheet, not a theme, so it does not count: a
        person who asked only for less motion still gets Streamlit's own
        colours and sizes, untouched.
        """
        return not (
            self.palette == DEFAULT_PALETTE
            and self.text_size == DEFAULT_TEXT_SIZE
            and not self.high_contrast
        )


# Every theme option this module may set. Listed in full so that switching
# away from a palette clears what it set: a key not named here is never
# touched, and a key named here is always either set or explicitly None.
MANAGED_KEYS: tuple[str, ...] = (
    "theme.base",
    "theme.primaryColor",
    "theme.backgroundColor",
    "theme.secondaryBackgroundColor",
    "theme.textColor",
    "theme.linkColor",
    "theme.linkUnderline",
    "theme.borderColor",
    "theme.showWidgetBorder",
    "theme.baseFontSize",
    "theme.baseFontWeight",
    "theme.dataframeHeaderBackgroundColor",
    "theme.dataframeBorderColor",
    "theme.sidebar.backgroundColor",
    "theme.sidebar.secondaryBackgroundColor",
    "theme.sidebar.textColor",
    "theme.sidebar.borderColor",
)


# The overlay a person with low vision asked for: black on white, or white on
# black, strong borders on every widget, underlined links, heavier type. The
# primary colours are chosen so white button text still reads on them.
HIGH_CONTRAST_LIGHT = {
    "theme.primaryColor": "#0000b3",
    "theme.backgroundColor": "#ffffff",
    "theme.secondaryBackgroundColor": "#e6e6e6",
    "theme.textColor": "#000000",
    "theme.linkColor": "#0000ee",
    "theme.borderColor": "#000000",
    "theme.dataframeHeaderBackgroundColor": "#d9d9d9",
    "theme.dataframeBorderColor": "#000000",
    "theme.sidebar.backgroundColor": "#ffffff",
    "theme.sidebar.secondaryBackgroundColor": "#e6e6e6",
    "theme.sidebar.textColor": "#000000",
    "theme.sidebar.borderColor": "#000000",
}
HIGH_CONTRAST_DARK = {
    "theme.primaryColor": "#1a56db",
    "theme.backgroundColor": "#000000",
    "theme.secondaryBackgroundColor": "#1f1f1f",
    "theme.textColor": "#ffffff",
    "theme.linkColor": "#9ecbff",
    "theme.borderColor": "#ffffff",
    "theme.dataframeHeaderBackgroundColor": "#262626",
    "theme.dataframeBorderColor": "#ffffff",
    "theme.sidebar.backgroundColor": "#000000",
    "theme.sidebar.secondaryBackgroundColor": "#1f1f1f",
    "theme.sidebar.textColor": "#ffffff",
    "theme.sidebar.borderColor": "#ffffff",
}


def theme_options(look: Look) -> dict[str, Any]:
    """Every managed theme option, set or None, for this look.

    A look that is Light, Regular and not high contrast maps every key to
    None, so an untouched machine sends Streamlit nothing and renders exactly
    as it did before this module; so does choosing Light on purpose, which is
    the same thing said out loud.
    """
    options: dict[str, Any] = {key: None for key in MANAGED_KEYS}
    if not look.themed():
        return options

    palette = PALETTE_BY_KEY[look.palette]
    options.update(
        {
            "theme.base": palette.base,
            "theme.primaryColor": palette.primary,
            "theme.backgroundColor": palette.background,
            "theme.secondaryBackgroundColor": palette.secondary,
            "theme.textColor": palette.text,
            "theme.borderColor": palette.border,
            "theme.sidebar.backgroundColor": palette.sidebar_background,
            "theme.sidebar.secondaryBackgroundColor": palette.sidebar_secondary,
            "theme.sidebar.textColor": palette.sidebar_text,
        }
    )
    if look.high_contrast:
        options.update(
            HIGH_CONTRAST_DARK if palette.base == "dark" else HIGH_CONTRAST_LIGHT
        )
        options["theme.showWidgetBorder"] = True
        options["theme.linkUnderline"] = True
        options["theme.baseFontWeight"] = 500

    _, pixels = TEXT_SIZES[look.text_size]
    if pixels != TEXT_SIZES[DEFAULT_TEXT_SIZE][1]:
        options["theme.baseFontSize"] = pixels
    return options


def flags(settings: Mapping[str, Any]) -> list[str]:
    """`--theme.*` arguments for the launcher, so the first paint is right."""
    out: list[str] = []
    for key, value in theme_options(Look.from_settings(settings)).items():
        if value is None:
            continue
        out += [f"--{key}", str(value).lower() if isinstance(value, bool) else str(value)]
    return out


def apply(look: Look) -> int:
    """Push this look into the running server's config. Returns changes made.

    The next rerun's session message carries the new theme, and the browser
    re-themes without a restart. `streamlit.config.set_option` is an internal
    API; the launcher flags are the supported path, and this is the one that
    makes a sidebar change take effect now rather than after a restart.
    """
    from streamlit import config

    changed = 0
    for key, value in theme_options(look).items():
        if config.get_option(key) != value:
            config.set_option(key, value)
            changed += 1
    return changed


def css(look: Look) -> str:
    """The little the theme cannot say: motion, and a focus ring that shows."""
    rules: list[str] = []
    if look.reduce_motion:
        rules.append(
            "*, *::before, *::after {"
            " animation-duration: 0.001s !important;"
            " animation-iteration-count: 1 !important;"
            " transition-duration: 0.001s !important;"
            " scroll-behavior: auto !important; }"
        )
    if look.high_contrast:
        palette = PALETTE_BY_KEY[look.palette]
        ring = "#ffffff" if palette.base == "dark" else "#000000"
        rules.append(
            f"*:focus-visible {{ outline: 3px solid {ring} !important;"
            " outline-offset: 2px !important; }"
        )
    return f"<style>{' '.join(rules)}</style>" if rules else ""


# ---------------------------------------------------------------------------
# Contrast, so the palettes are measured rather than eyeballed
# ---------------------------------------------------------------------------

def _channel(value: str) -> float:
    c = int(value, 16) / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (_channel(h[i : i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground: str, background: str) -> float:
    """WCAG contrast ratio, 1 to 21. AA body text is 4.5; AAA is 7."""
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# What the machine remembers
# ---------------------------------------------------------------------------

def current() -> Look:
    from ..library import read_settings

    return Look.from_settings(read_settings())


def save(look: Look) -> None:
    from ..library import read_settings, write_settings

    settings = read_settings()
    settings[THEME] = look.palette
    settings[TEXT_SIZE] = look.text_size
    settings[HIGH_CONTRAST] = look.high_contrast
    settings[REDUCE_MOTION] = look.reduce_motion
    write_settings(settings)


# ---------------------------------------------------------------------------
# Drawing it
# ---------------------------------------------------------------------------

def inject(look: Look) -> None:
    """The stylesheet for motion and focus, once per run, if there is one."""
    import streamlit as st

    sheet = css(look)
    if sheet:
        st.markdown(sheet, unsafe_allow_html=True)


def controls() -> None:
    """The Appearance controls, drawn inside the Settings section.

    A change is saved, applied to the server, and the page rerun, so the new
    look is on screen before the click has been let go of.
    """
    import streamlit as st

    look = current()
    st.markdown("**Appearance**")
    palette_labels = [p.label for p in PALETTES]
    palette_keys = [p.key for p in PALETTES]
    chosen_palette = st.selectbox(
        "Theme",
        options=palette_labels,
        index=palette_keys.index(look.palette),
        key="look-theme",
    )
    size_keys = list(TEXT_SIZES)
    chosen_size = st.radio(
        "Text size",
        options=size_keys,
        index=size_keys.index(look.text_size),
        format_func=lambda k: TEXT_SIZES[k][0],
        horizontal=True,
        key="look-text-size",
    )
    high_contrast = st.checkbox(
        "High contrast", value=look.high_contrast, key="look-high-contrast"
    )
    reduce_motion = st.checkbox(
        "Reduce motion", value=look.reduce_motion, key="look-reduce-motion"
    )
    st.caption(
        "Remembered on this machine. High contrast puts black on white, or "
        "white on black, with borders on every control and underlined links."
    )

    wanted = Look(
        palette=palette_keys[palette_labels.index(chosen_palette)],
        text_size=chosen_size,
        high_contrast=high_contrast,
        reduce_motion=reduce_motion,
    )
    if wanted != look:
        save(wanted)
        apply(wanted)
        st.rerun()
