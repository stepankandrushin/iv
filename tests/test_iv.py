"""python3 -m unittest discover tests: the key parser, what gets shown, and iv run in a pty."""

import fcntl
import importlib.machinery
import importlib.util
import os
import pty
import re
import select
import shutil
import struct
import tempfile
import termios
import threading
import time
import unittest
import zlib

IV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iv")
loader = importlib.machinery.SourceFileLoader("iv", IV)
spec = importlib.util.spec_from_loader("iv", loader)
iv = importlib.util.module_from_spec(spec)
loader.exec_module(iv)


def png(width=4, height=3):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def write_png(path, width=4, height=3):
    with open(path, "wb") as f:
        f.write(png(width, height))


class Pipe:
    """A named pipe that gives each reader a fresh PNG, the way a screen grabber's would."""

    def __init__(self, path):
        self.path = path
        self.reads = 0
        self.stopped = False
        os.mkfifo(path)
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            with open(self.path, "wb") as f:  # waits for a reader
                if self.stopped:
                    return
                # A new pipe takes the name before anything is written: opening this one again for
                # the next reader could carry on into this reader before it had seen the end of file.
                os.mkfifo(self.path + ".new")
                os.rename(self.path + ".new", self.path)
                self.reads += 1
                f.write(png(4 + self.reads, 3))

    def stop(self):
        self.stopped = True
        os.close(os.open(self.path, os.O_RDONLY | os.O_NONBLOCK))  # wakes serve() so that it returns


class Keys(unittest.TestCase):
    def test_moves(self):
        cases = {
            b" ": [1], b"\x1b[C\x1b[C": [1, 1], b"\x1bOB": [1], b"\x1b[6~": [1],
            b"\x7f": [-1], b"\x1b[D": [-1], b"\x1b[5~": [-1],
            b"gG": ["first", "last"], b"\x1b[H": ["first"], b"\x1b[4~": ["last"],
            b"q": ["quit"], b"\x1b": ["quit"], b"\x1b[27u": ["quit"], b"r": ["again"],
        }
        for data, expected in cases.items():
            self.assertEqual(list(iv.actions(data)), expected, data)

    def test_unknown_sequences_are_skipped_whole(self):
        self.assertEqual(list(iv.actions(b"\x1b[1;5C\x1bOPx ")), [1])


class Collect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in ("img10.png", "img2.PNG", "img1.jpg", ".hidden.png", "notes.txt"):
            open(os.path.join(self.dir, name), "w").close()
        os.mkdir(os.path.join(self.dir, "sub.png"))
        os.mkfifo(os.path.join(self.dir, "live.png"))  # not read: collect only stats it

    def tearDown(self):
        shutil.rmtree(self.dir)

    def names(self, files):
        return [os.path.basename(f) for f in files]

    def test_folder_in_natural_order(self):
        files, index = iv.collect([self.dir])
        self.assertEqual((self.names(files), index), (["img1.jpg", "img2.PNG", "img10.png"], 0))

    def test_one_image_opens_its_folder_at_it(self):
        files, index = iv.collect([os.path.join(self.dir, "img10.png")])
        self.assertEqual((len(files), index), (3, 2))

    def test_a_file_named_alone_is_shown_whatever_its_name(self):
        files, index = iv.collect([os.path.join(self.dir, "notes.txt")])
        self.assertEqual((self.names(files), index), (["notes.txt"], 0))

    def test_a_named_pipe_is_shown_only_when_named(self):
        pipe = os.path.join(self.dir, "live.png")
        self.assertEqual(self.names(iv.collect([pipe])[0]), ["live.png"])
        self.assertEqual(self.names(iv.collect([pipe, os.path.join(self.dir, "img1.jpg")])[0]),
                         ["live.png", "img1.jpg"])


@unittest.skipUnless(shutil.which("kitten"), "kitten is not installed")
class InPty(unittest.TestCase):
    """iv in a pty that answers icat's queries the way a kitty-graphics terminal does."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for i in range(1, 4):
            write_png(os.path.join(self.dir, f"p{i}.png"))
        self.pid = None
        self.pipe = None
        self.out = b""

    def start(self, *args):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 1000, 600))
            os.execvp("python3", ["python3", IV, *args])

    def tearDown(self):
        try:
            if self.pid:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
        if self.pipe:
            self.pipe.stop()
        shutil.rmtree(self.dir)

    def pump(self, until, timeout=10):
        end = time.time() + timeout
        while time.time() < end and not until():
            if not select.select([self.fd], [], [], 0.05)[0]:
                continue
            try:
                chunk = os.read(self.fd, 1 << 20)
            except OSError:
                return
            self.out += chunk
            # A real terminal answers after icat has set up its tty; an instant answer gets flushed.
            time.sleep(0.05)
            for m in re.finditer(rb"\x1b_G([^;\x1b]*)", chunk):
                keys = dict(kv.split(b"=", 1) for kv in m.group(1).split(b",") if b"=" in kv)
                if keys.get(b"a") == b"q":
                    os.write(self.fd, b"\x1b_Gi=" + keys.get(b"i", b"0") + b";OK\x1b\\")
            if b"\x1b[14t" in chunk:
                os.write(self.fd, b"\x1b[4;600;1000t")
            if b"\x1b[c" in chunk:
                os.write(self.fd, b"\x1b[?62;22c")

    def bar(self):
        bars = re.findall(rb"\x1b\[(\d+);1H\x1b\[2K\x1b\[7m ([^\x1b]*)\x1b\[27m", self.out)
        return (int(bars[-1][0]), bars[-1][1].decode().split("  ")) if bars else None

    def status(self):
        bar = self.bar()
        return (bar[0], bar[1][0]) if bar else None

    def press(self, key, expected):
        self.out = b""
        os.write(self.fd, key)
        self.pump(lambda: self.status() == expected)
        self.assertEqual(self.status(), expected, key)

    def quit(self):
        os.write(self.fd, b"q")
        self.pump(lambda: b"\x1b[?1049l" in self.out)
        _, status = os.waitpid(self.pid, 0)
        self.assertEqual(status, 0)
        self.assertTrue(self.out.endswith(b"\x1b[?25h\x1b[?1049l"), self.out[-80:])

    def test_keys_resize_and_quit(self):
        self.start(self.dir)
        self.pump(lambda: self.status() == (30, "1/3"))
        self.assertEqual(self.status(), (30, "1/3"))
        self.assertIn(b"a=T", self.out)  # icat displayed the image
        self.press(b" ", (30, "2/3"))
        self.press(b"\x1b[C", (30, "3/3"))
        os.write(self.fd, b" ")  # at the last image: nothing moves, nothing is drawn
        self.out = b""
        self.pump(lambda: False, timeout=1)
        self.assertIsNone(self.status())
        self.press(b"\x1b[D\x1b[D", (30, "1/3"))
        self.out = b""
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 80, 800, 400))
        os.kill(self.pid, 28)  # SIGWINCH, which the pty sends only to its foreground group
        self.pump(lambda: self.status() == (20, "1/3"))
        self.assertEqual(self.status(), (20, "1/3"))
        self.quit()

    def test_a_pipe_is_read_on_arrival_and_on_r_not_on_resize(self):
        self.pipe = Pipe(os.path.join(self.dir, "screen.png"))
        self.start(self.pipe.path, os.path.join(self.dir, "p1.png"))
        size = lambda width: iv.human_size(len(png(width, 3)))
        shown = lambda reads: lambda: (self.pipe.reads == reads and self.bar()
                                       and self.bar()[1][2] == size(4 + reads))
        self.pump(shown(1))
        self.assertEqual(self.bar()[1][:3], ["1/2", "screen.png", size(5)])
        self.assertIn("r again", self.bar()[1][-4])
        self.assertIn(b"a=T", self.out)  # icat displayed what came through the pipe
        self.out = b""
        os.write(self.fd, b"r")
        self.pump(shown(2))
        self.assertEqual((self.pipe.reads, self.bar()[1][2]), (2, size(6)))
        self.assertIn(b"a=T", self.out)
        self.out = b""
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 80, 800, 400))
        os.kill(self.pid, 28)
        self.pump(lambda: self.status() == (20, "1/2"))
        self.assertEqual((self.status(), self.pipe.reads, self.bar()[1][2]), ((20, "1/2"), 2, size(6)))
        self.assertIn(b"a=T", self.out)  # the image the pipe gave last, drawn again
        self.press(b" ", (20, "2/2"))
        self.press(b"\x1b[D", (20, "1/2"))
        self.pump(shown(3))
        self.assertEqual(self.pipe.reads, 3)  # read again on coming back to it
        self.quit()

    def test_a_pipe_without_a_writer_waits_and_ctrl_c_quits(self):
        path = os.path.join(self.dir, "nobody.png")
        os.mkfifo(path)
        self.start(path)
        self.pump(lambda: self.bar() and self.bar()[1][2] == "reading…")
        self.assertEqual(self.bar()[1][:3], ["1/1", "nobody.png", "reading…"])
        os.write(self.fd, b"\x03")
        self.pump(lambda: b"\x1b[?1049l" in self.out)
        _, status = os.waitpid(self.pid, 0)
        self.assertEqual(status, 0)
        self.assertTrue(self.out.endswith(b"\x1b[?25h\x1b[?1049l"), self.out[-80:])


if __name__ == "__main__":
    unittest.main()
