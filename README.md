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

A named pipe given by name is shown too, on its own, for a program that gives each reader a fresh
image (a screen grab, say): iv reads it each time it comes to it and again on r, so what it shows
is live; a resized window redraws what the pipe gave last. While nothing writes into the pipe, iv
waits with "reading…" in the bar, and Ctrl-C quits. A folder's pipes are left out.

| Keys | |
|---|---|
| Space, →, ↓, PageDown, Enter, l, j, n | next |
| Backspace, ←, ↑, PageUp, h, k, p | previous |
| Home, g / End, G | first / last |
| r | again: a pipe is read anew, a file drawn again |
| q, Esc, Ctrl-C | quit |

A folder's images are its .jpg, .jpeg, .png, .gif, .webp, .bmp, .tif, .tiff, .heic, .heif and .avif
files, hidden ones left out, sorted by name with numbers in number order (img2 before img10).
At the first or the last image a key that would go past it does nothing. GIFs play.

## What it needs

- `kitten`, which comes with [kitty](https://sw.kovidgoyal.net/kitty/) and does the drawing
  (`kitten icat`); Install below gets it. It decodes JPEG, PNG, GIF, WebP, BMP and TIFF itself,
  and the others through ImageMagick if that is installed.
- A terminal that speaks the kitty graphics protocol: Ghostty, kitty, WezTerm, Konsole. herdr
  draws a pane's images in such a terminal, so iv works inside herdr too.
- Python 3.9 or newer, standard library only.

## Install

First the dependency. Besides python3, the one program iv runs is `kitten icat`, and kitty brings
it — the kitty terminal itself is not needed. kitty's installer fetches its latest release and
unpacks it, without a trip to kitty's site; with `launch=n` it does not start kitty when it is
done, which a machine with no screen wants:

```sh
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
```

On Linux that leaves kitten in `~/.local/kitty.app/bin`, off the PATH; one symlink puts it where
iv finds it. On macOS it lands in `/Applications`, where iv looks for it itself, so no symlink is
needed:

```sh
ln -sf ~/.local/kitty.app/bin/kitten ~/.local/bin/
```

Then iv, which is one file, and an alias so the command is `iv`. These put it into the startup
file of the shell you run — `~/.zshrc` for zsh, `~/.bashrc` for bash, `~/.profile` for anything
else — once, however often they are run:

```sh
git clone https://github.com/stepankandrushin/iv ~/src/iv
case $SHELL in *zsh|*bash) f=~/.$(basename "$SHELL")rc ;; *) f=~/.profile ;; esac
grep -qs '^alias iv=' "$f" || echo "alias iv='python3 ~/src/iv/iv'" >> "$f"
```

fish keeps its startup file elsewhere, `~/.config/fish/config.fish`; without an alias at all,
`python3 ~/src/iv/iv` is the same thing.

## How it works

iv switches to the terminal's alternate screen, as a full-screen program does. For each image it
deletes the image on screen, clears the screen and runs
`kitten icat --stdin=no --place=<columns>x<rows-1>@0x0 <file>`, which scales the image down to fit
above the bottom line and centres it; then it writes the bar. A named pipe it reads itself, to the
end, and hands to `kitten icat --stdin=yes`: given the path, icat or the terminal would open the
pipe again, and a second open of such a pipe is a second image. Keys pressed while an image is
being drawn are added up, so holding Space does not queue a redraw for each image passed. A
resized window is redrawn. On quit it deletes the image and returns to the screen as it was.

`python3 -m unittest discover tests` runs the tests; one of them runs iv in a pseudo-terminal
that answers icat's queries, and is skipped where kitten is not installed.

## License

MIT, see [LICENSE](LICENSE).
