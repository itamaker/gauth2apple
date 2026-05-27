#!/usr/bin/env python3
"""
gauth2apple — split a Google Authenticator export QR into individual
otpauth:// QR codes that Apple Passwords (via iPhone Camera) can import.

Cross-platform GUI (Tkinter for dialogs; results rendered as a temp HTML
page opened in the default browser). Fully local, no network calls.

Dependencies:
    pip install "qrcode[pil]" pyzbar pillow
    # zbar system library (for pyzbar):
    #   macOS:   brew install zbar
    #   Linux:   apt-get install libzbar0   (or your distro's equivalent)
    #   Windows: bundled inside the pyzbar wheel

Run:
    python3 gauth2apple_gui.py
"""

import base64
import html
import io
import os
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from pathlib import Path

import qrcode
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from pyzbar.pyzbar import decode as zbar_decode
except ImportError:
    zbar_decode = None


IS_MACOS = sys.platform == "darwin"
APP_TITLE = "gauth2apple"


# ---------------- protobuf parsing ----------------

def _read_varint(buf, pos):
    result, shift = 0, 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _parse_fields(buf):
    fields, pos = {}, 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        no, wire = tag >> 3, tag & 0x7
        if wire == 0:
            val, pos = _read_varint(buf, pos)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            val = buf[pos:pos + length]
            pos += length
        else:
            raise ValueError(f"unsupported wire type {wire}")
        fields.setdefault(no, []).append((wire, val))
    return fields


ALGO = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
DIGITS = {0: 6, 1: 6, 2: 8}
OTP_TYPE = {0: "totp", 1: "hotp", 2: "totp"}


def parse_migration(data_b64: str):
    data_b64 = urllib.parse.unquote(data_b64)
    pad = (-len(data_b64)) % 4
    raw = base64.b64decode(data_b64 + "=" * pad)
    fields = _parse_fields(raw)
    accounts = []
    for _, blob in fields.get(1, []):
        f = _parse_fields(blob)
        secret = f[1][0][1] if 1 in f else b""
        name = f[2][0][1].decode("utf-8", "ignore") if 2 in f else ""
        issuer = f[3][0][1].decode("utf-8", "ignore") if 3 in f else ""
        algo = ALGO.get(f[4][0][1] if 4 in f else 1, "SHA1")
        digits = DIGITS.get(f[5][0][1] if 5 in f else 1, 6)
        otp_type = OTP_TYPE.get(f[6][0][1] if 6 in f else 2, "totp")
        counter = f[7][0][1] if 7 in f else 0
        b32 = base64.b32encode(secret).decode("ascii").rstrip("=")
        label = f"{issuer}:{name}" if issuer else name
        params = {"secret": b32, "algorithm": algo, "digits": str(digits)}
        if issuer:
            params["issuer"] = issuer
        if otp_type == "hotp":
            params["counter"] = str(counter)
        url = f"otpauth://{otp_type}/{urllib.parse.quote(label)}?" + urllib.parse.urlencode(params)
        accounts.append({"label": label, "issuer": issuer, "name": name, "url": url})
    return accounts


def extract_data_from_url(migration_url: str) -> str:
    q = urllib.parse.urlparse(migration_url).query
    return urllib.parse.parse_qs(q).get("data", [""])[0]


def decode_qr_image(path: str) -> str:
    if zbar_decode is None or Image is None:
        raise RuntimeError(
            "pyzbar / Pillow are required to decode QR images.\n"
            "  pip install pyzbar pillow\n"
            "  macOS:   brew install zbar\n"
            "  Linux:   apt-get install libzbar0"
        )
    results = zbar_decode(Image.open(path))
    for r in results:
        text = r.data.decode("utf-8", "ignore")
        if text.startswith("otpauth-migration://"):
            return text
    raise ValueError(f"No Google Authenticator migration QR code found in {Path(path).name}")


# ---------------- Wi-Fi toggle (macOS only) ----------------

def get_wifi_device():
    if not IS_MACOS:
        return None
    try:
        out = subprocess.check_output(["networksetup", "-listallhardwareports"], text=True, timeout=5)
    except Exception:
        return None
    for blk in out.split("\n\n"):
        if "Wi-Fi" in blk:
            for line in blk.splitlines():
                if line.startswith("Device:"):
                    return line.split(":", 1)[1].strip()
    return None


def get_wifi_power(device: str):
    try:
        out = subprocess.check_output(["networksetup", "-getairportpower", device], text=True, timeout=5)
        return "On" in out
    except Exception:
        return None


def set_wifi_power(device: str, on: bool):
    subprocess.check_call(["networksetup", "-setairportpower", device, "on" if on else "off"], timeout=5)


# ---------------- Tkinter dialogs ----------------

def make_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    try:
        root.title(APP_TITLE)
    except Exception:
        pass
    return root


def dialog_choose_action(root: tk.Tk) -> str:
    """Custom modal: returns 'image' / 'url' / 'quit'."""
    dlg = tk.Toplevel(root)
    dlg.title(APP_TITLE)
    dlg.resizable(False, False)
    dlg.transient(root)

    result = {"value": "quit"}

    tk.Label(
        dlg,
        text="Google Authenticator → Apple Passwords\n\nChoose an input method:",
        justify="center",
        padx=20,
        pady=16,
    ).pack()

    btns = tk.Frame(dlg)
    btns.pack(pady=(0, 16), padx=20)

    def pick(value):
        result["value"] = value
        dlg.destroy()

    tk.Button(btns, text="Choose Image", width=14, command=lambda: pick("image")).pack(side="left", padx=6)
    tk.Button(btns, text="Paste URL", width=14, command=lambda: pick("url")).pack(side="left", padx=6)
    tk.Button(btns, text="Cancel", width=10, command=lambda: pick("quit")).pack(side="left", padx=6)

    dlg.protocol("WM_DELETE_WINDOW", lambda: pick("quit"))
    dlg.update_idletasks()
    # Center on screen
    w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    x = (dlg.winfo_screenwidth() - w) // 2
    y = (dlg.winfo_screenheight() - h) // 2
    dlg.geometry(f"+{x}+{y}")

    dlg.grab_set()
    root.wait_window(dlg)
    return result["value"]


def dialog_pick_images(root: tk.Tk) -> list:
    paths = filedialog.askopenfilenames(
        parent=root,
        title="Select Google Authenticator export QR screenshot(s)",
        filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"), ("All files", "*.*")],
    )
    return list(paths) if paths else []


def dialog_input_url(root: tk.Tk):
    return simpledialog.askstring(
        APP_TITLE,
        "Paste the otpauth-migration:// URL:",
        parent=root,
    )


def dialog_ask_disable_wifi(root: tk.Tk) -> bool:
    return messagebox.askyesno(
        APP_TITLE,
        "For safety, turn Wi-Fi off before processing the QR codes?\n\n"
        "(It will be restored when this tool exits.)",
        parent=root,
    )


def dialog_info(root: tk.Tk, msg: str):
    messagebox.showinfo(APP_TITLE, msg, parent=root)


def dialog_error(root: tk.Tk, msg: str):
    messagebox.showerror(APP_TITLE, msg, parent=root)


# ---------------- HTML rendering ----------------

def qr_data_uri(url: str, size: int = 8) -> str:
    qr = qrcode.QRCode(box_size=size, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def render_html(accounts) -> str:
    cards = []
    for i, acc in enumerate(accounts, 1):
        cards.append(f"""
        <div class="card">
            <img src="{qr_data_uri(acc['url'])}" alt="QR" />
            <div class="label">{i}. {html.escape(acc['label'] or '(unnamed)')}</div>
            <div class="issuer">{html.escape(acc['issuer'] or '')}</div>
        </div>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>gauth2apple — {len(accounts)} accounts</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "SF Pro Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    background: #f5f5f7; margin: 0; padding: 24px;
    color: #1d1d1f;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .sub {{ color: #6e6e73; font-size: 14px; margin-bottom: 18px; }}
  .warn {{
    background: #fff8e1; border-left: 4px solid #f5a623;
    padding: 12px 16px; border-radius: 8px;
    margin-bottom: 24px; font-size: 14px; line-height: 1.5;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
  }}
  .card {{
    background: white; border-radius: 14px; padding: 16px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  }}
  .card img {{
    width: 100%; max-width: 240px; height: auto;
    image-rendering: pixelated;
  }}
  .label {{ font-weight: 600; margin-top: 10px; font-size: 14px; word-break: break-all; }}
  .issuer {{ color: #6e6e73; font-size: 12px; margin-top: 2px; }}
  .footer {{
    margin-top: 30px; padding-top: 20px;
    border-top: 1px solid #d2d2d7;
    color: #86868b; font-size: 12px;
  }}
</style>
</head>
<body>
  <h1>Google Authenticator → Apple Passwords</h1>
  <div class="sub">Decoded <strong>{len(accounts)}</strong> account(s)</div>
  <div class="warn">
    <strong>How to use</strong>: Point the iPhone Camera at any QR below, then tap "Open in Passwords"
    when it appears. Apple Passwords will save that account.<br>
    <strong>Security</strong>: This page is generated locally and uploads nothing. Close the tab to clear it.
    Disabling network connectivity before scanning is recommended.
  </div>
  <div class="grid">
    {"".join(cards)}
  </div>
  <div class="footer">This page lives in a temp directory and is removed after you dismiss the dialog.</div>
</body>
</html>
"""


def open_in_browser(html_str: str) -> str:
    fd, path = tempfile.mkstemp(prefix="gauth2apple_", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html_str)
    webbrowser.open(f"file://{path}")
    return path


# ---------------- Main flow ----------------

def collect_migration_urls(root: tk.Tk) -> list:
    action = dialog_choose_action(root)
    if action == "quit":
        sys.exit(0)
    if action == "image":
        paths = dialog_pick_images(root)
        if not paths:
            sys.exit(0)
        return [decode_qr_image(p) for p in paths]
    if action == "url":
        url = dialog_input_url(root)
        if not url:
            sys.exit(0)
        return [url]
    sys.exit(0)


def main():
    root = make_root()

    # 1) Optionally turn Wi-Fi off (macOS only)
    wifi_dev = get_wifi_device() if IS_MACOS else None
    was_on = get_wifi_power(wifi_dev) if wifi_dev else None
    if wifi_dev and was_on and dialog_ask_disable_wifi(root):
        try:
            set_wifi_power(wifi_dev, False)
        except Exception as e:
            dialog_error(root, f"Failed to turn Wi-Fi off: {e}")

    # 2) Gather one or more migration URLs
    try:
        urls = collect_migration_urls(root)
    except Exception as e:
        dialog_error(root, str(e))
        sys.exit(1)

    # 3) Parse and merge
    accounts = []
    for u in urls:
        if not u.startswith("otpauth-migration://"):
            dialog_error(root, f"Not a Google Authenticator migration QR:\n{u[:80]}")
            sys.exit(1)
        data = extract_data_from_url(u)
        if not data:
            dialog_error(root, "No `data` parameter in the URL")
            sys.exit(1)
        try:
            accounts.extend(parse_migration(data))
        except Exception as e:
            dialog_error(root, f"Parse failed: {e}")
            sys.exit(1)

    if not accounts:
        dialog_info(root, "No accounts decoded")
        sys.exit(0)

    # 4) Render and open in the browser
    html_path = open_in_browser(render_html(accounts))

    # 5) Follow-up instructions
    wifi_restored_note = (
        " and restore Wi-Fi"
        if (wifi_dev and was_on and get_wifi_power(wifi_dev) is False)
        else ""
    )
    dialog_info(
        root,
        f"Generated {len(accounts)} QR code(s); opened in your default browser.\n\n"
        f'Scan each QR with the iPhone Camera and tap "Open in Passwords" to import.\n\n'
        f"Click OK to delete the temp file{wifi_restored_note}.",
    )

    # 6) Clean up the temp HTML
    try:
        os.unlink(html_path)
    except Exception:
        pass

    # 7) Restore Wi-Fi if we turned it off
    if wifi_dev and was_on and get_wifi_power(wifi_dev) is False:
        try:
            set_wifi_power(wifi_dev, True)
        except Exception:
            pass

    root.destroy()


if __name__ == "__main__":
    main()
