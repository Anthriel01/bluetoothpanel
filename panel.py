"""Telefondan Bluetooth ile gelen mesajı ekranda 5 sn gösteren panel.

Kullanım:
    python panel.py --list            # COM portlarını listele
    python panel.py                   # tüm Bluetooth COM portlarını dinle
    python panel.py COM5              # sadece belirli portu dinle
    python panel.py --test "merhaba"  # Bluetooth olmadan paneli dene
"""
import argparse
import ctypes
import queue
import threading
import time
import tkinter as tk

import serial
import serial.tools.list_ports

SHOW_SECONDS = 5
FLUSH_AFTER = 0.6  # satır sonu gelmezse bu kadar sn sonra mesajı göster

messages = queue.Queue()


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
                            messages.put(line.decode("utf-8", "replace").strip())
                elif buf and now - last > FLUSH_AFTER:
                    messages.put(buf.decode("utf-8", "replace").strip())
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--test", metavar="MESAJ")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    KEY = "#010101"  # bu renk tamamen şeffaf olur
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", KEY)
    root.attributes("-alpha", 0.72)
    root.configure(bg=KEY)
    canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
    canvas.pack()
    root.withdraw()
    state = {"hide_at": 0.0}

    def rounded(x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return canvas.create_polygon(pts, smooth=True, **kw)

    def show(text):
        canvas.delete("all")
        pad = 20
        t = canvas.create_text(pad, pad, text=text, anchor="nw", fill="#39ff6a",
                               font=("Segoe UI", 13, "bold"), width=320)
        x1, y1, x2, y2 = canvas.bbox(t)
        w, h = x2 + pad, y2 + pad
        bubble = rounded(1, 1, w - 1, h - 1, min(h // 2, 30), fill="#0b130e", outline="#2fd45a")
        canvas.tag_lower(bubble)
        canvas.config(width=w, height=h)
        root.update_idletasks()
        x = (root.winfo_screenwidth() - w) // 2
        root.geometry(f"{w}x{h}+{x}+110")
        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        click_through(root)
        state["hide_at"] = time.time() + SHOW_SECONDS

    def poll():
        try:
            while True:
                show(messages.get_nowait())
        except queue.Empty:
            pass
        if state["hide_at"] and time.time() >= state["hide_at"]:
            root.withdraw()
            state["hide_at"] = 0.0
        root.after(100, poll)

    if args.test:
        messages.put(args.test)
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
    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
