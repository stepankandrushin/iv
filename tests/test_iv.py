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
import time
import unittest
import zlib

IV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iv")
loader = importlib.machinery.SourceFileLoader("iv", IV)
spec = importlib.util.spec_from_loader("iv", loader)
iv = importlib.util.module_from_spec(spec)
loader.exec_module(iv)


def write_png(path, width=4, height=3):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class Keys(unittest.TestCase):
    def test_moves(self):
        cases = {
            b" ": [1], b"\x1b[C\x1b[C": [1, 1], b"\x1bOB": [1], b"\x1b[6~": [1],
            b"\x7f": [-1], b"\x1b[D": [-1], b"\x1b[5~": [-1],
            b"gG": ["first", "last"], b"\x1b[H": ["first"], b"\x1b[4~": ["last"],
            b"q": ["quit"], b"\x1b": ["quit"], b"\x1b[27u": ["quit"],
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


@unittest.skipUnless(shutil.which("kitten"), "kitten is not installed")
class InPty(unittest.TestCase):
    """iv in a pty that answers icat's queries the way a kitty-graphics terminal does."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for i in range(1, 4):
            write_png(os.path.join(self.dir, f"p{i}.png"))
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 1000, 600))
            os.execvp("python3", ["python3", IV, self.dir])
        self.out = b""

    def tearDown(self):
        try:
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
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

    def status(self):
        bars = re.findall(rb"\x1b\[(\d+);1H\x1b\[2K\x1b\[7m ([^\x1b]*)\x1b\[27m", self.out)
        return (int(bars[-1][0]), bars[-1][1].split(b"  ")[0].decode()) if bars else None

    def press(self, key, expected):
        self.out = b""
        os.write(self.fd, key)
        self.pump(lambda: self.status() == expected)
        self.assertEqual(self.status(), expected, key)

    def test_keys_resize_and_quit(self):
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
        os.write(self.fd, b"q")
        self.pump(lambda: b"\x1b[?1049l" in self.out)
        _, status = os.waitpid(self.pid, 0)
        self.assertEqual(status, 0)
        self.assertTrue(self.out.endswith(b"\x1b[?25h\x1b[?1049l"), self.out[-80:])


if __name__ == "__main__":
    unittest.main()
