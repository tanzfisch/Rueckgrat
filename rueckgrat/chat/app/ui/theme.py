import sys
import flet as ft

BG = "#121212"
SURFACE = "#1E1E1E"
SURFACE_2 = "#262626"
SURFACE_3 = "#2A2A2A"
SURFACE_4 = "#343434"
TEAL = "#00424c"
TEAL_FILL = "#0b6b78"
TEAL_HANDLE = "#06424a"
TEXT = "#E0E0E0"
TEXT_DIM = "#606060"
ERROR = "#8f0000"
RADIUS = 16

SIZE_FACTOR = 1.2 if sys.platform not in ("android", "ios") else 1.0

def apply_theme(page: ft.Page):
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=TEAL,
            on_primary=TEXT,
            surface=SURFACE,
            on_surface=TEXT,
            error=ERROR,
        ),
        font_family="Segoe UI",
        text_theme=ft.TextTheme(
            display_large=ft.TextStyle(size=57*SIZE_FACTOR, color=TEXT),
            display_medium=ft.TextStyle(size=45*SIZE_FACTOR, color=TEXT),
            display_small=ft.TextStyle(size=36*SIZE_FACTOR, color=TEXT),
            headline_large=ft.TextStyle(size=32*SIZE_FACTOR, color=TEXT),
            headline_medium=ft.TextStyle(size=28*SIZE_FACTOR, color=TEXT),
            headline_small=ft.TextStyle(size=24*SIZE_FACTOR, color=TEXT),
            title_large=ft.TextStyle(size=22*SIZE_FACTOR, color=TEXT),
            title_medium=ft.TextStyle(size=16*SIZE_FACTOR, color=TEXT),
            title_small=ft.TextStyle(size=14*SIZE_FACTOR, color=TEXT),
            body_large=ft.TextStyle(size=16*SIZE_FACTOR, color=TEXT),
            body_medium=ft.TextStyle(size=14*SIZE_FACTOR, color=TEXT),
            body_small=ft.TextStyle(size=12*SIZE_FACTOR, color=TEXT),
            label_large=ft.TextStyle(size=14*SIZE_FACTOR, color=TEXT),
            label_medium=ft.TextStyle(size=12*SIZE_FACTOR, color=TEXT),
            label_small=ft.TextStyle(size=11*SIZE_FACTOR, color=TEXT),
        ),      
    )

# text font + color emoji fallback (#68). code blocks keep markdown's monospace default
TEXT_FONT = "DejaVu Sans"
EMOJI_FALLBACK = ["Noto Color Emoji"]

def _md_text(size: float) -> ft.TextStyle:
    return ft.TextStyle(size=size*SIZE_FACTOR, color=TEXT, font_family=TEXT_FONT, font_family_fallback=EMOJI_FALLBACK)

# sizes follow flutter_markdown's defaults (body_medium for text, headline_small..body_large for headings)
MARKDOWN_STYLE = ft.MarkdownStyleSheet(
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

STYLES = {
    "one_line_bubble": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
    "chat_bubble": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
    "code": dict(bgcolor=SURFACE_2, border_radius=RADIUS, padding=16, border=ft.Border.all(2, "#8D8D8D")),
    "text": dict(bgcolor=ft.Colors.TRANSPARENT, padding=0),
    "chat_user": dict(bgcolor=TEAL, border_radius=RADIUS, padding=10),
    "chat_assistant": dict(bgcolor=SURFACE_4, border_radius=RADIUS, padding=10),
    "chat_error": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=10),
    "input_container": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=0),
    "flat_button": dict(bgcolor=ft.Colors.TRANSPARENT),
    "button": dict(bgcolor=SURFACE, color=TEXT, style=ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: SURFACE,
            ft.ControlState.FOCUSED: SURFACE_3,
            ft.ControlState.PRESSED: "#777777",
            ft.ControlState.SELECTED: TEAL,
        },
        color=TEXT,
        padding=20,
        shape=ft.RoundedRectangleBorder(radius=RADIUS),
        overlay_color=ft.Colors.TRANSPARENT,
    )),
    "icon_button": dict(
        bgcolor=SURFACE,
        color=TEXT,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: SURFACE,
                ft.ControlState.FOCUSED: SURFACE_3,
                ft.ControlState.PRESSED: "#777777",
                ft.ControlState.SELECTED: TEAL,
            },
            color=TEXT,
            padding=0,
            shape=ft.RoundedRectangleBorder(radius=RADIUS),
            overlay_color=ft.Colors.TRANSPARENT,
    )),    
    "field": dict(
        bgcolor=SURFACE,
        color=TEXT,
        border_radius=RADIUS,
        border_color=ft.Colors.TRANSPARENT,
        focused_border_color=TEAL,
        content_padding=10,
    ),
    "input_box": dict(bgcolor=ft.Colors.TRANSPARENT, border_color=ft.Colors.TRANSPARENT, color=TEXT),
    "label": dict(color=TEXT),
    "label_slider": ft.TextStyle(color=TEXT_DIM, size=12),
    "contact_card": dict(bgcolor=SURFACE, border_radius=RADIUS, padding=10),
    "overlay_scrim": dict(bgcolor=ft.Colors.with_opacity(150 / 255, ft.Colors.BLACK)),
    "overlay_dialog": dict(bgcolor=TEAL, border_radius=RADIUS),
    "dropdown": dict(bgcolor=SURFACE, color=TEXT, border_radius=RADIUS, focused_border_color=TEAL),
}


def style(control, name: str):
    for k, v in STYLES[name].items():
        setattr(control, k, v)
    return control