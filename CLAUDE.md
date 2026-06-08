# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file, cross-platform desktop tool that converts a Google Authenticator "Export accounts" QR (the proprietary `otpauth-migration://` format, which packs N accounts into one QR) into N standard one-account-per-QR `otpauth://` codes that Apple Passwords can import via the iPhone Camera. Everything is local — no network calls, no third-party services. The entire program is `gauth2apple_gui.py`.

## Commands

```bash
# Run from source (Python 3.8+)
pip install -r requirements.txt
python3 gauth2apple_gui.py

# zbar system library is a hard runtime dependency of pyzbar (not pip-installable on macOS/Linux):
#   macOS:   brew install zbar
#   Linux:   sudo apt-get install libzbar0 python3-tk   (tk is also needed for the GUI)
#   Windows: bundled inside the pyzbar wheel
```

There is **no test suite, linter config, or build script** in the repo. Builds happen only in CI (see Releases below). To exercise a code path manually, run the GUI; the parsing functions (`parse_migration`, `extract_data_from_url`, `decode_qr_image`) are plain module-level functions you can import and call from a REPL.

## Architecture

The program is a linear pipeline, top-to-bottom in `gauth2apple_gui.py`, gated by Tkinter dialogs:

1. **Input** — either decode a screenshot QR via pyzbar (`decode_qr_image`) or take a pasted URL. Both must start with `otpauth-migration://`. Multiple inputs are merged into one account list.
2. **Hand-rolled protobuf parser** (`_read_varint`, `_parse_fields`, `parse_migration`) — this is the heart of the tool and the most non-obvious part. The migration payload is a protobuf `MigrationPayload` message, parsed **without any `.proto` file or protobuf library** — just raw varint/length-delimited wire decoding. Only wire types 0 (varint) and 2 (length-delimited) are handled; anything else raises. Field numbers are hardcoded (1=secret, 2=name, 3=issuer, 4=algorithm, 5=digits, 6=type, 7=counter), and the `ALGO`/`DIGITS`/`OTP_TYPE` dicts map the enum integers to strings. If Google ever changes the schema, this is where it breaks.
3. **Re-encode** — each raw secret is base32-encoded and rebuilt into a standard `otpauth://totp/<issuer>:<name>?secret=...&issuer=...&algorithm=...&digits=...` URL. That exact format is what Apple Passwords' "Open in Passwords" hook recognizes.
4. **Render** — `qrcode` generates one QR per URL as an inline base64 PNG data-URI embedded in a self-contained HTML page (`render_html`), written to a temp file and opened in the default browser (`open_in_browser`).
5. **Cleanup** — the temp HTML is `os.unlink`'d when the user dismisses the final dialog.

### macOS Wi-Fi toggle

On macOS only, the tool offers to turn Wi-Fi off before decoding (`get_wifi_device`/`get_wifi_power`/`set_wifi_power`, via `networksetup`) and restores the prior state on exit. Guard any networking-related changes with the existing `IS_MACOS` checks — this path is a no-op on Linux/Windows.

### Optional dependencies are caught, not required at import

`PIL.Image` and `pyzbar.pyzbar.decode` are imported inside `try/except` and set to `None` on failure. `decode_qr_image` raises a helpful install message if they're missing. This lets the URL-paste path work even when zbar isn't installed. Preserve that — don't move these to top-level hard imports.

## Releases

Tagging triggers `.github/workflows/release.yml`, which runs PyInstaller (`--collect-all pyzbar` is required so the zbar binary is bundled) on three runners and publishes a GitHub Release:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Intentional CI constraints (don't "fix" these without reason — they're deliberate, see commit history): macOS builds **arm64 only** — no Intel/universal2 artifact, because GitHub's free Intel Mac runners queue too long; Intel Mac users are directed to run from source. macOS binaries are unsigned, so the README documents the Gatekeeper `xattr -d com.apple.quarantine` workaround.

## Security context

This tool decodes high-value TOTP seeds. Keep the local-only guarantee intact: no network calls, no clipboard writes, no telemetry. The generated HTML embeds secrets as QR images — keep it in a temp dir and keep the post-dialog cleanup. When touching parsing or rendering, be conservative; a bug here can silently corrupt or leak 2FA secrets.
