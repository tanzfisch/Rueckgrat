import flet as ft
from app.ui import theme

from app.common import get_logger
logger = get_logger()

PODIUM = 3
PODIUM_ORDER = (1, 0, 2)        # the places left to right: silver, gold in the middle, bronze
STEP_HEIGHTS = (56, 40, 28)     # gold's step is the highest, like at the olympics
IMAGE_SIZE = 72


def price_text(finding: dict) -> str:
    """1,299.00 NZD"""
    try:
        return f"{float(finding.get('price')):,.2f} {finding.get('currency') or ''}".strip()
    except (TypeError, ValueError):
        return ""


class PriceView(ft.Column):
    """the price ranking under an assistant answer (the hub's PriceFinderTool): the best three on a podium (2nd left,
    1st in the middle and highest, 3rd right) with the product's picture, price and shop, more finds in a list under it.
    a tap on a find opens its shop page"""
    def __init__(self, prices: dict):
        super().__init__(spacing=10, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.prices = prices
        findings = [finding for finding in prices.get("findings") or [] if isinstance(finding, dict)]
        podium = findings[:PODIUM]
        self.controls = [
            ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS, color=theme.GOLD, size=20),
                    ft.Text(prices.get("query") or "", color=theme.TEXT, weight=ft.FontWeight.BOLD, expand=True, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS, font_family=theme.TEXT_FONT, font_family_fallback=theme.EMOJI_FALLBACK)],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([self._place(place, podium[place]) for place in PODIUM_ORDER if place < len(podium)],
                   spacing=8, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.END),
        ]
        if findings[PODIUM:]:
            self.controls.append(ft.Column([self._row(place, finding) for place, finding in enumerate(findings[PODIUM:], PODIUM + 1)],
                                           spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))

    def _image(self, finding: dict) -> ft.Control:
        placeholder = ft.Icon(ft.Icons.SHOPPING_BAG_OUTLINED, size=IMAGE_SIZE // 2, color=theme.TEXT_DIM)
        image = finding.get("image")
        content = ft.Image(src=image, width=IMAGE_SIZE, height=IMAGE_SIZE, fit=ft.BoxFit.CONTAIN, border_radius=6,
                           error_content=placeholder) if image else placeholder
        return ft.Container(content=content, height=IMAGE_SIZE, alignment=ft.Alignment.CENTER)

    def _place(self, place: int, finding: dict) -> ft.Column:
        """one podium place: the find's card on its step in the medal's colour"""
        medal = theme.MEDALS[place]
        card = ft.Container(
            content=ft.Column([
                self._image(finding),
                ft.Text(finding.get("title") or "", color=theme.TEXT, size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER, font_family=theme.TEXT_FONT, font_family_fallback=theme.EMOJI_FALLBACK),
                ft.Text(price_text(finding), color=theme.TEXT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Text(finding.get("shop") or "", color=theme.TEXT_DIM, size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, bgcolor=theme.SURFACE, border=ft.Border.all(2, medal),
            border_radius=ft.BorderRadius(theme.RADIUS // 2, theme.RADIUS // 2, 0, 0),
            ink=True, tooltip=finding.get("note") or finding.get("url"), on_click=self._opener(finding),
        )
        step = ft.Container(
            content=ft.Text(str(place + 1), color=theme.ON_MEDAL, size=20, weight=ft.FontWeight.BOLD),
            height=STEP_HEIGHTS[place], bgcolor=medal, alignment=ft.Alignment.CENTER,
        )
        return ft.Column([card, step], spacing=0, tight=True, expand=1, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _row(self, place: int, finding: dict) -> ft.Container:
        """one find of the list under the podium"""
        details = " · ".join(part for part in (finding.get("shop"), finding.get("note")) if part)
        return ft.Container(
            content=ft.Row([
                ft.Text(f"{place}.", color=theme.TEXT_DIM, width=24),
                ft.Column([
                    ft.Text(finding.get("title") or "", color=theme.TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            font_family=theme.TEXT_FONT, font_family_fallback=theme.EMOJI_FALLBACK),
                    ft.Text(details, color=theme.TEXT_DIM, size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=0, tight=True, expand=True),
                ft.Text(price_text(finding), color=theme.TEXT, weight=ft.FontWeight.BOLD),
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=16, color=theme.TEXT_DIM),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=8, top=6, right=8, bottom=6), bgcolor=theme.SURFACE, border_radius=theme.RADIUS // 2,
            ink=True, tooltip=finding.get("url"), on_click=self._opener(finding),
        )

    def _opener(self, finding: dict):
        """the click handler that opens the find's shop page, None without a web link"""
        url = str(finding.get("url") or "")
        if not url.startswith(("https://", "http://")):
            return None

        async def open_url(e):
            try:
                await ft.UrlLauncher().launch_url(url)
            except Exception as ex:
                logger.error(f"opening {url} failed: {ex}")
        return open_url
