"""Telefondan Bluetooth ile gelen mesajı ekranda 5 sn gösteren panel.

Kullanım:
    python panel.py --list            # COM portlarını listele
    python panel.py                   # tüm Bluetooth COM portlarını dinle
    python panel.py COM5              # sadece belirli portu dinle
    python panel.py --test "merhaba"  # Bluetooth olmadan paneli dene
"""
import argparse
import ctypes
import math
import queue
import re
import threading
import time
import tkinter as tk
import unicodedata

import serial
import serial.tools.list_ports
from PIL import Image, ImageDraw, ImageFont, ImageTk

SHOW_SECONDS = 5
FLUSH_AFTER = 0.6  # satır sonu gelmezse bu kadar sn sonra mesajı göster
MAX_VISIBLE = 5    # ekranda aynı anda en fazla bu kadar balon durur
FADE_IN = 0.25
FADE_OUT = 0.40
MAX_ALPHA = 0.95
GAP = 10           # balonlar arası boşluk (96 dpi pikseli)
TOP = 110          # ilk balonun ekranın üstünden uzaklığı
TEXT_PT = 13
MAX_TEXT_W = 320

BUBBLE_FILL = "#fff3d6"
BUBBLE_EDGE = "#d9b779"
TEXT_RGB = (0x3b, 0x2a, 0x1a)
KEY = "#010101"    # bu renk tamamen şeffaf olur

FONT_TEXT = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_EMOJI = r"C:\Windows\Fonts\seguiemj.ttf"

ENCODING = "auto"  # auto: önce UTF-8, olmazsa Windows-1254 (Türkçe)

messages = queue.Queue()


def decode(raw):
    """Telefondan gelen baytları metne çevir (UTF-8 ya da Türkçe Windows-1254)."""
    if ENCODING == "auto":
        try:
            s = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            s = raw.decode("cp1254", "replace")
    else:
        s = raw.decode(ENCODING, "replace")
    # i + birleşik nokta gibi ayrık yazılmış ç ğ ı İ ö ş ü harflerini tek karaktere çevir
    s = unicodedata.normalize("NFC", s)
    s = "".join(" " if c == "\t" else c for c in s
                if c == "\t" or (unicodedata.category(c) not in ("Cc", "Cs") and c != "\ufeff"))
    return s.strip()


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2B1B\u2B1C"
                      "\u231A\u231B\u23E9-\u23F3]")
EMOJI_JUNK = re.compile("[\uFE0F\u200D\u20E3\U0001F3FB-\U0001F3FF]")  # varyasyon/ton/birleştirici


def make_fonts(px):
    def load(path):
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            return ImageFont.truetype("arial.ttf", px)
    text = load(FONT_TEXT)
    return text, load(FONT_EMOJI)


def render_text(text, fonts, max_w):
    """Metni (renkli emojiler dahil) saydam bir resme çiz."""
    font, efont = fonts
    text = EMOJI_JUNK.sub("", " ".join(text.split()))
    atoms = []  # (karakter, emoji_mi, genişlik)
    for ch in text:
        em = bool(EMOJI_RE.match(ch))
        atoms.append((ch, em, (efont if em else font).getlength(ch)))

    lines, cur, cw, brk = [], [], 0.0, 0
    for a in atoms:
        cur.append(a)
        cw += a[2]
        if a[0] == " ":
            brk = len(cur)
            continue
        if cw > max_w and len(cur) > 1:
            if brk:
                line, cur = cur[:brk], cur[brk:]
            else:
                line, cur = cur[:-1], cur[-1:]
            lines.append(line)
            cw, brk = sum(x[2] for x in cur), 0
    lines.append(cur)
    lines = [[a for a in ln] for ln in lines]
    for ln in lines:
        while ln and ln[-1][0] == " ":
            ln.pop()

    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 2
    width = max(1, math.ceil(max(sum(a[2] for a in ln) for ln in lines)))
    img = Image.new("RGBA", (width, line_h * len(lines)), TEXT_RGB + (0,))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        x, base = 0.0, i * line_h + ascent
        for ch, em, w in ln:
            if ch != " ":
                if em:
                    d.text((x, base), ch, font=efont, embedded_color=True, anchor="ls")
                else:
                    d.text((x, base), ch, font=font, fill=TEXT_RGB + (255,), anchor="ls")
            x += w
    return img


def list_ports():
    for p in serial.tools.list_ports.comports():
        print(f"{p.device}\t{p.description}")


def reader(port):
    buf = b""
    last = time.time()
    while True:
        try:
            ser = serial.Serial(port, 9600, timeout=0.2)
        except serial.SerialException as e:
            print(f"{port} açılamadı: {e} - 3 sn sonra tekrar denenecek")
            time.sleep(3)
            continue
        print(f"{port} dinleniyor...")
        try:
            while True:
                data = ser.read(256)
                now = time.time()
                if data:
                    buf += data
                    last = now
                    while True:
                        idx = min((buf.find(s) for s in (b"\n", b"\r") if s in buf), default=-1)
                        if idx < 0:
                            break
                        line, buf = buf[:idx], buf[idx + 1:]
                        if line.strip():
                            messages.put(decode(line))
                elif buf and now - last > FLUSH_AFTER:
                    messages.put(decode(buf))
                    buf = b""
        except (serial.SerialException, OSError):
            print("Bağlantı koptu, bekleniyor...")
            buf = b""
            time.sleep(2)


def click_through(root):
    """Pencereyi tıklanamaz ve odak çalmaz yap (film oynatıcıyı bozmasın)."""
    GWL_EXSTYLE = -20
    flags = 0x80000 | 0x20 | 0x08000000 | 0x80  # LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | flags)


class Bubble:
    """Tek bir mesaj balonu: kendi penceresi, kendi solma animasyonu var."""

    def __init__(self, root, text, fonts, scale, now):
        self.pad = round(20 * scale)
        img = render_text(text, fonts, round(MAX_TEXT_W * scale))
        self.w = img.width + 2 * self.pad
        self.h = img.height + 2 * self.pad
        self.born = now
        self.die_at = now + FADE_IN + SHOW_SECONDS
        self.y = None
        self.target = 0.0
        self.alpha = -1.0
        self.shown_y = None
        self.scale = scale

        self.win = win = tk.Toplevel(root)
        win.withdraw()
        win.overrideredirect(True)
        win.configure(bg=KEY)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY)
        win.attributes("-alpha", 0.0)
        canvas = tk.Canvas(win, bg=KEY, highlightthickness=0, bd=0, width=self.w, height=self.h)
        canvas.pack()
        r = min(self.h // 2, round(30 * scale))
        x1, y1, x2, y2 = 1, 1, self.w - 1, self.h - 1
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        canvas.create_polygon(pts, smooth=True, fill=BUBBLE_FILL, outline=BUBBLE_EDGE, width=2)
        self.photo = ImageTk.PhotoImage(img, master=win)  # referansı tut, yoksa silinir
        canvas.create_image(self.pad, self.pad, image=self.photo, anchor="nw")
        self.x = (win.winfo_screenwidth() - self.w) // 2
        win.update_idletasks()

    def update(self, now, dt):
        if self.y is None:  # ilk karede hedefin biraz üstünden kayarak gelsin
            self.y = self.target - 22 * self.scale
        self.y += (self.target - self.y) * (1 - math.exp(-dt * 14))

        fade_in = min(1.0, (now - self.born) / FADE_IN)
        fade_in = 1 - (1 - fade_in) ** 3
        fade_out = 1 - min(1.0, max(0.0, (now - self.die_at) / FADE_OUT))
        alpha = round(MAX_ALPHA * fade_in * fade_out, 2)

        y = round(self.y)
        if y != self.shown_y:
            self.win.geometry(f"{self.w}x{self.h}+{self.x}+{y}")
            if self.shown_y is None:
                self.win.deiconify()
                self.win.attributes("-topmost", True)
                click_through(self.win)
            self.shown_y = y
        if alpha != self.alpha:
            self.win.attributes("-alpha", alpha)
            self.alpha = alpha

    def expired(self, now):
        return now >= self.die_at + FADE_OUT

    def destroy(self):
        self.win.destroy()


def main():
    global ENCODING
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--test", metavar="MESAJ", action="append",
                    help="Bluetooth olmadan dene (birden fazla kez verilebilir)")
    ap.add_argument("--encoding", default="auto",
                    help="gelen metnin kodlaması: auto (varsayılan), utf-8, cp1254, iso-8859-9 ...")
    args = ap.parse_args()
    ENCODING = args.encoding

    if args.list:
        list_ports()
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()
    dpi = root.winfo_fpixels("1i")
    scale = dpi / 96
    fonts = make_fonts(round(TEXT_PT * dpi / 72))
    bubbles = []
    clock = {"last": time.monotonic()}

    def add(text, now):
        bubbles.append(Bubble(root, text, fonts, scale, now))
        alive = [b for b in bubbles if now < b.die_at]
        for b in alive[:-MAX_VISIBLE]:  # fazla balonları en eskiden başlayıp erit
            b.die_at = now

    def tick():
        now = time.monotonic()
        dt = min(now - clock["last"], 0.1)
        clock["last"] = now
        try:
            while True:
                add(messages.get_nowait(), now)
        except queue.Empty:
            pass
        for b in [b for b in bubbles if b.expired(now)]:
            b.destroy()
            bubbles.remove(b)
        y = TOP * scale
        for b in bubbles:
            b.target = y
            b.update(now, dt)
            y += b.h + GAP * scale
        root.after(16 if bubbles else 100, tick)

    for t in args.test or []:
        messages.put(t)
    if args.port:
        ports = [args.port]
    else:
        bt = [p for p in serial.tools.list_ports.comports()
              if "bluetooth" in p.description.lower()]
        # Gelen (incoming) portun adresi 000000000000'dır; giden portu açmak telefona bağlanmaya çalışır
        incoming = [p for p in bt if "&000000000000_" in (p.hwid or "")]
        ports = [p.device for p in (incoming or bt)]
    for port in ports:
        threading.Thread(target=reader, args=(port,), daemon=True).start()
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
