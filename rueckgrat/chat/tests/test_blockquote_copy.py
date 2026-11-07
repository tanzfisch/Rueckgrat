"""blockquote copy text, and that a quote stays markdown next to ordinary text and code."""
from app.ui import theme
from app.ui.widgets.bubbles import ChatBubble, quote_text, split_blockquotes
import flet as ft


def test_quote_text_drops_one_marker_per_line():
    assert quote_text("> Hello\n> world") == "Hello\nworld"
    assert quote_text("> first\n>\n> second") == "first\n\nsecond"
    assert quote_text("> > nested") == "> nested"


def test_split_keeps_neighbouring_text_and_a_gap_inside_the_quote():
    parts = split_blockquotes("Intro\n\n> one\n>\n> two\n\nOutro\n")
    assert [part["type"] for part in parts] == ["text", "quote", "text"]
    assert quote_text(parts[1]["value"]) == "one\n\ntwo"
    assert "Outro" in parts[2]["value"]
    assert ">" not in parts[0]["value"]


def test_a_quote_marker_inside_a_code_fence_is_not_a_quote():
    bubble = ChatBubble("assistant", "Hi\n\n> Lyric line\n>\n> second line\n\n```\n> not a quote\n```\n")
    quotes = [c for c in bubble.body.controls if isinstance(c, ft.Stack) and c.data == {"id": "quote"}]
    codes = [c for c in bubble.body.controls if isinstance(c, ft.Container) and (c.data or {}).get("id") == "code"]
    assert len(quotes) == 1 and len(codes) == 1
    button = quotes[0].controls[1]
    assert button.icon == ft.Icons.CONTENT_COPY
    assert button.tooltip == "Copy"
    markdown = quotes[0].controls[0]
    assert markdown.value.startswith(">")
    assert markdown.md_style_sheet is theme.MARKDOWN_STYLE
    assert theme.MARKDOWN_STYLE.blockquote_decoration.bgcolor == theme.BLOCKQUOTE
    assert theme.MARKDOWN_STYLE.blockquote_decoration.border_radius == 16
