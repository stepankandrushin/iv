# iv

Look through images in the terminal one at a time: Space or → for the next, ← or Backspace for the
one before, q to quit. Each image fills the window, with a bar at the bottom: its number, its name
and its size. It works over ssh, since the terminal on your side draws the image.

```
iv               the images in the current folder
iv <folder>      the images in that folder
iv <image>       the images in that image's folder, starting at it
iv <a> <b> ...   those images; a folder among them adds the images in it
```

| Keys | |
|---|---|
| Space, →, ↓, PageDown, Enter, l, j, n | next |
| Backspace, ←, ↑, PageUp, h, k, p | previous |
| Home, g / End, G | first / last |
| q, Esc, Ctrl-C | quit |

A folder's images are its .jpg, .jpeg, .png, .gif, .webp, .bmp, .tif, .tiff, .heic, .heif and .avif
files, hidden ones left out, sorted by name with numbers in number order (img2 before img10).
At the first or the last image a key that would go past it does nothing. GIFs play.

## What it needs

- `kitten`, which comes with [kitty](https://sw.kovidgoyal.net/kitty/) and does the drawing
  (`kitten icat`); on Linux it can be installed alone from kitty's release page. It decodes JPEG,
  PNG, GIF, WebP, BMP and TIFF itself, and the others through ImageMagick if that is installed.
- A terminal that speaks the kitty graphics protocol: Ghostty, kitty, WezTerm, Konsole. herdr
  draws a pane's images in such a terminal, so iv works inside herdr too.
- Python 3.9 or newer, standard library only.

## Install

It is one file. Run it as `python3 <path>/iv`, or make an alias:

```sh
alias iv='python3 ~/src/iv/iv'
```

## How it works

iv switches to the terminal's alternate screen, as a full-screen program does. For each image it
deletes the image on screen, clears the screen and runs
`kitten icat --stdin=no --place=<columns>x<rows-1>@0x0 <file>`, which scales the image down to fit
above the bottom line and centres it; then it writes the bar. Keys pressed while an image is
being drawn are added up, so holding Space does not queue a redraw for each image passed. A
resized window is redrawn. On quit it deletes the image and returns to the screen as it was.

`python3 -m unittest discover tests` runs the tests; one of them runs iv in a pseudo-terminal
that answers icat's queries, and is skipped where kitten is not installed.
