# Test Prompts

Used during development or for demo purposes.

## code prompts

```
Create a small Python project I can download: an interactive Mandelbrot and Julia set explorer using pygame and numpy.
Files:
- fractal_explorer/main.py: starts the app and runs the event loop
- fractal_explorer/fractals.py: a module with mandelbrot(width, height, center, zoom, max_iter) and julia(...) that return iteration counts as numpy arrays
- fractal_explorer/render.py: turns iteration counts into a coloured pygame surface with a few selectable palettes
- requirements.txt
- README.md: how to install, run and use the controls
Controls: left click zooms in on the point, right click zooms out, arrow keys pan, J toggles between Mandelbrot and Julia (using the point under the mouse as c), C cycles palettes, +/- change max iterations, R resets the view, and S saves a screenshot as PNG.
Show the current zoom, center and iterations in the window title.
```


## prompts to trigger specific tools and tool combinations

### write_file

```
Create a small website for my bakery with an index.html and a css/style.css file I can download.
```

### websearch, fetch_url

```
Please look up the latest in AI news. during your search have a look at  bild.de as well
```

### date_calc

```
how many days until the year ends?
```

### wikipedia, show_map

```
where is the Eifel Tower?
```

### generate_image, take_photo

```
Take a selfie of yourself at the beach and also make me an image of a sunset over the ocean.
```


