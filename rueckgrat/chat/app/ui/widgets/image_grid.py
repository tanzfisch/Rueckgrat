import flet as ft
from app.ui import theme
from .image import Image
from .image_overlay import ImageOverlay

TILE = 200          # max edge of a grid tile, more than one image
SINGLE_MAX = 400    # max longer side of a single image
MAX_TILES = 4       # 2x2 visible, the last one shows "+n" for the rest
COLUMNS = 2
SPACING = 4


class ImageGrid(ft.Row):
    """the images of a message: one image full size (centred, like before), several as small square tiles in a 2x2 grid.
    more than MAX_TILES: the last tile is dimmed with "+n" for the hidden ones, a tap opens it"""
    def __init__(self, image_paths: list[str], alignment: ft.Alignment = ft.Alignment.CENTER_LEFT):
        super().__init__()
        self.image_paths = list(image_paths)
        if len(self.image_paths) == 1:
            # one image, its longer side at most SINGLE_MAX, smaller if the bubble is narrower
            self.controls = [ft.Container(content=Image(image_path=self.image_paths[0], max_edge=SINGLE_MAX), alignment=alignment, expand=True)]
            self.expand = True
            return
        tiles = [self._tile(path) for path in self.image_paths[:MAX_TILES]]
        hidden = len(self.image_paths) - MAX_TILES
        if hidden > 0:
            tiles[-1] = self._more_tile(self.image_paths[MAX_TILES - 1], hidden)
        rows = []
        for i in range(0, len(tiles), COLUMNS):
            row = tiles[i:i + COLUMNS]
            row += [ft.Container(expand=1) for _ in range(COLUMNS - len(row))]   # a lone last tile keeps the size of the others
            rows.append(ft.Row(row, spacing=SPACING))
        # the tiles expand with the bubble, but not beyond TILE
        grid = ft.Column(rows, spacing=SPACING, tight=True, width=COLUMNS * TILE + (COLUMNS - 1) * SPACING)
        self.controls = [ft.Container(content=grid, alignment=alignment, expand=True)]

    @staticmethod
    def _square(content: ft.Control) -> ft.Control:
        return ft.Container(content=content, expand=1, aspect_ratio=1,
                            border_radius=theme.RADIUS // 2, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    @staticmethod
    def _tile(path: str) -> ft.Control:
        return ImageGrid._square(Image(image_path=path, fit=ft.BoxFit.COVER, fill=True))

    @staticmethod
    def _more_tile(path: str, hidden: int) -> ft.Control:
        async def open_image(e):
            await ImageOverlay.open(e.page, path)
        cover = ft.Container(content=ft.Text(f"+{hidden}", size=28 * theme.SIZE_FACTOR, weight=ft.FontWeight.BOLD, color=theme.ON_SCRIM),
                             bgcolor=theme.SCRIM_SOFT, alignment=ft.Alignment.CENTER, left=0, top=0, right=0, bottom=0,
                             on_click=open_image)
        return ImageGrid._square(ft.Stack([Image(image_path=path, fit=ft.BoxFit.COVER, fill=True), cover]))
