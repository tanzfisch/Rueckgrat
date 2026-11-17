# Test Prompts

Used during development or for demo purposes.

## large prompts

```
Create an audiobook for me about the Younger Dryas impact hypothesis, in four chapters:

1. **The Younger Dryas:** what it was, when it happened (about 12,900 to 11,700 years ago), and why it was such a fascinating period of sudden climate change and upheaval.
2. **The impact hypothesis:** what the theory claims, the evidence its supporters point to, and the main criticisms from other scientists.
3. **Graham Hancock:** his ideas about an advanced ancient civilisation that was wiped out during the Younger Dryas, and how mainstream archaeology responds to them.
4. **Could it happen again?** Some speculation if a similar catastrophe could strike today and how our current civilisation would cope.

Research each topic first, write each chapter to its own file, then turn all four into a single audio file in your voice and give me the download link.
```


```
Create a small Python project: an interactive Mandelbrot and Julia set explorer using pygame and numpy.
Files:
- fractal_explorer/main.py: starts the app and runs the event loop
- fractal_explorer/fractals.py: a module with mandelbrot(width, height, center, zoom, max_iter) and julia(...) that return iteration counts as numpy arrays
- fractal_explorer/render.py: turns iteration counts into a coloured pygame surface with a few selectable palettes
- requirements.txt
- README.md: how to install, run and use the controls
Controls: left click zooms in on the point, right click zooms out, arrow keys pan, J toggles between Mandelbrot and Julia (using the point under the mouse as c), C cycles palettes, +/- change max iterations, R resets the view, and S saves a screenshot as PNG.
Show the current zoom, center and iterations in the window title.
```

```
Create a small C++17 project: an interactive Mandelbrot and Julia set explorer using SDL2, built with CMake.
Files:
- fractal_explorer/CMakeLists.txt: builds the `fractal_explorer` executable and finds SDL2 with find_package
- fractal_explorer/src/main.cpp: creates the window and runs the event loop
- fractal_explorer/src/fractals.h and fractals.cpp: functions mandelbrot(width, height, center, zoom, maxIter) and julia(width, height, center, zoom, maxIter, c) that return the iteration counts as a std::vector<int>, using std::complex<double> and spreading the rows over std::thread
- fractal_explorer/src/render.h and render.cpp: turn iteration counts into an RGBA pixel buffer for an SDL texture, with a few selectable palettes
- fractal_explorer/README.md: how to install SDL2 on Debian (apt install libsdl2-dev), how to build with cmake and how to run it, plus the controls
Controls: left click zooms in on the point, right click zooms out, arrow keys pan, J toggles between Mandelbrot and Julia (using the point under the mouse as c), C cycles palettes, +/- change max iterations, R resets the view, and S saves a screenshot as BMP with SDL_SaveBMP.
Show the current zoom, center and iterations in the window title.
After writing the files, build the project with cmake to check that it compiles and fix any errors.
```

## prompts to trigger specific tools and tool combinations

### task

```
create a task that runs every day "find me the best price for Kenwood Chef KVC3100"
```

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

### poll

I'd like to start a new project but I don't know what it should be about. Please create a multi round questionaire to guide me.
