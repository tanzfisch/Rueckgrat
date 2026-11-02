"""the single place for colours and styles, in a dark and a light palette.

use it as a module: `from app.ui import theme`, then theme.TEXT, theme.STYLES["button"], theme.icon("menu").
pages are built anew on every visit, so reading theme.X while building always gets the active mode.
apply_theme(page, mode) switches the mode: the palette names below, STYLES and MARKDOWN_STYLE are
rebuilt and the flet theme is set; open pages then have to be rebuilt (the settings page does that).
"""
import os
import sys
import flet as ft

ASSETS_DIR = os.getenv("FLET_ASSETS_DIR") or "assets"
DARK, LIGHT = "dark", "light"
DEFAULT_MODE = DARK

PALETTES = {
    DARK: dict(
        BACKGROUND="#121212",
        SURFACE="#1E1E1E",
        SURFACE_2="#262626",           # code blocks
        SURFACE_3="#2A2A2A",           # selector buttons, tool tiles, dividers
        SURFACE_4="#343434",           # assistant bubbles
        SURFACE_FIELD="#2C2C2C",       # filled fields of the profile pages and the voice selector
        PRESSED="#777777",
        CODE_BORDER="#8D8D8D",
        TEAL="#00424c",                # user bubbles, one line bubbles, dialogs
        TEAL_FILL="#0b6b78",           # primary colour, selected tabs, "reconnected" strip
        TEAL_BRIGHT="#5aa2ac",         # active translate panel
        TEAL_HANDLE="#06424a",
        ACCENT="#0D7377",              # switches and focused fields of the profile pages
        FOCUS="#00424c",               # focused field border
        TEXT="#E0E0E0",
        TEXT_DIM="#606060",
        TEXT_LABEL="#C8C8C8",          # row labels of the profile pages
        ON_ACCENT="#E0E0E0",           # text on TEAL_FILL and ERROR strips
        ERROR="#8f0000",
        WARNING=ft.Colors.AMBER,
        CODE_THEME=ft.MarkdownCodeTheme.ATOM_ONE_DARK,   # syntax colours in code blocks
        WALLPAPER="wallpaper_dark.jpg",
        ICON_SUFFIX="_light",          # light drawn icons on the dark background
        SCHEME={},                     # flutter's own role colours
    ),
    LIGHT: dict(
        BACKGROUND="#F4F6F6",
        SURFACE="#BCC7C9",             # buttons and fields: a clearly darker grey than the background
        SURFACE_2="#EEF1F1",
        SURFACE_3="#B3BEC1",
        SURFACE_4="#E6EAEB",
        SURFACE_FIELD="#C3CDCF",
        PRESSED="#9AA5A7",
        CODE_BORDER="#9AA5A7",
        TEAL="#CFE8EB",
        TEAL_FILL="#0b6b78",
        TEAL_BRIGHT="#0b6b78",
        TEAL_HANDLE="#9FCFD5",
        ACCENT="#0D7377",
        FOCUS="#0b6b78",
        TEXT="#1B1F20",
        TEXT_DIM="#5F6B6D",
        TEXT_LABEL="#3A4446",
        ON_ACCENT="#FFFFFF",
        ERROR="#B3261E",
        WARNING="#B26A00",
        CODE_THEME=ft.MarkdownCodeTheme.ATOM_ONE_LIGHT,
        WALLPAPER="wallpaper.png",
        ICON_SUFFIX="",                # the dark drawn icons
        # flutter's light role colours are near white: input bars, cards, input bar icons, switch track and border
        SCHEME=dict(
            surface_container_high="#C8D2D4",
            surface_container="#D3DBDD",
            surface_container_highest="#B3BEC1",
            on_surface_variant="#3A4446",
            outline="#5F6B6D",
        ),
    ),
}

# the same in both modes
TRANSPARENT = ft.Colors.TRANSPARENT
SCRIM = ft.Colors.with_opacity(0.85, ft.Colors.BLACK)        # full screen image viewer
SCRIM_SOFT = ft.Colors.with_opacity(0.6, ft.Colors.BLACK)    # round button over a picture
ON_SCRIM = ft.Colors.WHITE
# material roles: flutter resolves them from the active flet theme
INPUT_BAR = ft.Colors.SURFACE_CONTAINER_HIGH                 # message / prompt input bars
CARD = ft.Colors.SURFACE_CONTAINER
TEXT_VARIANT = ft.Colors.ON_SURFACE_VARIANT

RADIUS = 16
SIZE_FACTOR = 1.2 if sys.platform not in ("android", "ios") else 1.0

# text font + color emoji fallback (#68). code blocks keep markdown's monospace default
TEXT_FONT = "DejaVu Sans"
EMOJI_FALLBACK = ["Noto Color Emoji"]

# the names of the active palette, filled in by set_mode()
BACKGROUND = SURFACE = SURFACE_2 = SURFACE_3 = SURFACE_4 = SURFACE_FIELD = PRESSED = CODE_BORDER = ""
TEAL = TEAL_FILL = TEAL_BRIGHT = TEAL_HANDLE = ACCENT = FOCUS = ""
TEXT = TEXT_DIM = TEXT_LABEL = ON_ACCENT = ERROR = WARNING = CODE_THEME = WALLPAPER = ICON_SUFFIX = ""
SCHEME: dict = {}

mode = DEFAULT_MODE
STYLES: dict = {}
MARKDOWN_STYLE: ft.MarkdownStyleSheet = None


def is_dark() -> bool:
    return mode == DARK


def icon(name: str) -> str:
    """an icon drawn in both colours, e.g. icon("menu"): menu_light.png in dark mode, menu.png in light mode"""
    return f"{ASSETS_DIR}/icons/{name}{ICON_SUFFIX}.png"


def wallpaper() -> str:
    return f"{ASSETS_DIR}/icons/{WALLPAPER}"


def field_border(radius: float = RADIUS, focused_color: str | None = None) -> dict:
    """outlined text field or dropdown border: invisible, coloured while focused (flet 1.0 replaced border_radius, border_color and focused_border_color with this)"""
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(border_radius=radius, side=ft.BorderSide(color=TRANSPARENT)),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=radius, side=ft.BorderSide(width=2, color=focused_color or FOCUS)),
    }


def _md_text(size: float) -> ft.TextStyle:
    return ft.TextStyle(size=size*SIZE_FACTOR, color=TEXT, font_family=TEXT_FONT, font_family_fallback=EMOJI_FALLBACK)


def _markdown_style() -> ft.MarkdownStyleSheet:
    # sizes follow flutter_markdown's defaults (body_medium for text, headline_small..body_large for headings)
    return ft.MarkdownStyleSheet(
        p_text_style=_md_text(14),             # paragraphs and list items
        list_bullet_text_style=_md_text(14),
        blockquote_text_style=_md_text(14),
        table_head_text_style=_md_text(14),
        table_body_text_style=_md_text(14),
        h1_text_style=_md_text(24),
        h2_text_style=_md_text(22),
        h3_text_style=_md_text(16),
        h4_text_style=_md_text(16),
        h5_text_style=_md_text(16),
        h6_text_style=_md_text(16),
    )


def _button_style(padding) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: SURFACE,
            ft.ControlState.FOCUSED: SURFACE_3,
            ft.ControlState.PRESSED: PRESSED,
            ft.ControlState.SELECTED: TEAL,
        },
        color=TEXT,
        padding=padding,
        shape=ft.RoundedRectangleBorder(radius=RADIUS),
        overlay_color=TRANSPARENT,
    )


def _styles() -> dict:
    return {
        "one_line_bubble": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
        "chat_bubble": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
        "code": dict(bgcolor=SURFACE_2, border_radius=RADIUS, padding=16, border=ft.Border.all(2, CODE_BORDER)),
        "text": dict(bgcolor=TRANSPARENT, padding=0),
        "chat_user": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
        "chat_assistant": dict(bgcolor=SURFACE_4, border_radius=RADIUS, padding=10),
        "chat_error": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=10),
        "input_container": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=0),
        "flat_button": dict(bgcolor=TRANSPARENT),
        "button": dict(bgcolor=SURFACE, color=TEXT, style=_button_style(20)),
        "icon_button": dict(bgcolor=SURFACE, color=TEXT, style=_button_style(0)),
        "field": dict(
            bgcolor=SURFACE,
            color=TEXT,
            border=field_border(),
            content_padding=10,
        ),
        "input_box": dict(bgcolor=TRANSPARENT, border=ft.NoInputBorder(), color=TEXT),
        "label": dict(color=TEXT),
        "label_slider": ft.TextStyle(color=TEXT_DIM, size=12),
        "section_heading": ft.TextStyle(color=TEXT, size=18*SIZE_FACTOR, weight=ft.FontWeight.BOLD),   # settings and contact profile sections
        "contact_card": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=10),
        "overlay_scrim": dict(bgcolor=ft.Colors.with_opacity(150 / 255, ft.Colors.BLACK)),
        "overlay_dialog": dict(bgcolor=TEAL, border_radius=RADIUS),
        "dropdown": dict(bgcolor=SURFACE, color=TEXT, border=field_border()),
    }


def set_mode(new_mode: str | None = None):
    """makes a palette the active one: its names (theme.TEXT, ...), STYLES and MARKDOWN_STYLE. unknown modes are dark"""
    global mode, MARKDOWN_STYLE
    mode = new_mode if new_mode in PALETTES else DEFAULT_MODE
    globals().update(PALETTES[mode])
    STYLES.clear()                     # in place, a dict imported elsewhere stays current
    STYLES.update(_styles())
    MARKDOWN_STYLE = _markdown_style()


def _flet_theme() -> ft.Theme:
    s = SIZE_FACTOR
    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=TEAL_FILL,
            on_primary=ON_ACCENT,
            surface=SURFACE,
            on_surface=TEXT,
            error=ERROR,
            **SCHEME,
        ),
        scaffold_bgcolor=BACKGROUND,
        font_family="Segoe UI",
        text_theme=ft.TextTheme(
            display_large=ft.TextStyle(size=57*s, color=TEXT),
            display_medium=ft.TextStyle(size=45*s, color=TEXT),
            display_small=ft.TextStyle(size=36*s, color=TEXT),
            headline_large=ft.TextStyle(size=32*s, color=TEXT),
            headline_medium=ft.TextStyle(size=28*s, color=TEXT),
            headline_small=ft.TextStyle(size=24*s, color=TEXT),
            title_large=ft.TextStyle(size=22*s, color=TEXT),
            title_medium=ft.TextStyle(size=16*s, color=TEXT),
            title_small=ft.TextStyle(size=14*s, color=TEXT),
            body_large=ft.TextStyle(size=16*s, color=TEXT),
            body_medium=ft.TextStyle(size=14*s, color=TEXT),
            body_small=ft.TextStyle(size=12*s, color=TEXT),
            label_large=ft.TextStyle(size=14*s, color=TEXT),
            label_medium=ft.TextStyle(size=12*s, color=TEXT),
            label_small=ft.TextStyle(size=11*s, color=TEXT),
        ),
    )


def apply_theme(page: ft.Page, new_mode: str | None = None):
    """on startup with the stored mode, and when the user switches it. None keeps the active mode"""
    if new_mode is not None:
        set_mode(new_mode)
    page.theme_mode = ft.ThemeMode.DARK if mode == DARK else ft.ThemeMode.LIGHT
    page.bgcolor = BACKGROUND
    page.theme = _flet_theme()
    page.dark_theme = _flet_theme()


def style(control, name: str):
    for k, v in STYLES[name].items():
        setattr(control, k, v)
    return control


set_mode(DEFAULT_MODE)
