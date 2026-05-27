# gauth2apple

**Split a Google Authenticator export QR into individual `otpauth://` QR codes that Apple Passwords can import.**

Google Authenticator's "Export accounts" feature packs every selected account into **one** custom `otpauth-migration://` QR. Apple Passwords / the iPhone Camera don't understand that format — they only accept the standard one-account-per-QR `otpauth://` URLs.

`gauth2apple` takes that single migration QR (or the URL inside it) and **fans it out into N individual standard QR codes**, one per account, displayed in your browser. Point the iPhone Camera at each QR and tap **"Open in Passwords"** to import.

Everything runs locally. No network calls, no clipboard, no third-party services.

## What it actually does

```
  ┌──────────────────────┐                            ┌──────────────────┐
  │ Google Authenticator │                            │ otpauth://...    │ ──▶ iPhone Camera
  │ export QR (one big   │  ──gauth2apple──▶  fan-out │ otpauth://...    │ ──▶ "Open in
  │  otpauth-migration://│      decodes &             │ otpauth://...    │     Passwords"
  │  with N accounts)    │      base32-encodes        │ ... (N total)    │
  └──────────────────────┘                            └──────────────────┘
```

Concretely:

1. Reads `otpauth-migration://offline?data=<base64>` (from a screenshot or pasted URL).
2. Base64-decodes the payload and parses the protobuf `MigrationPayload` message.
3. For each `OtpParameters` entry, base32-encodes the raw secret and rebuilds a standard URL:
   ```
   otpauth://totp/<issuer>:<name>?secret=<base32>&issuer=<issuer>&algorithm=SHA1&digits=6
   ```
4. Renders one QR image per URL and opens them all in your default browser as a local HTML page.

## Platforms

| OS      | Status | Notes                                                                     |
|---------|--------|---------------------------------------------------------------------------|
| macOS   | ✅     | Tkinter UI. Bonus: offers to disable Wi-Fi before decoding, restores after. |
| Linux   | ✅     | Tkinter UI. Disable network manually for the offline-recommended workflow. |
| Windows | ✅     | Tkinter UI. Disable network manually for the offline-recommended workflow. |

## Install / run

### Option A — Download a prebuilt binary

Grab the latest release from the [Releases page](../../releases/latest):

- macOS Apple Silicon (M1/M2/M3/M4): `gauth2apple-macos-arm64.zip` — unzip and run `gauth2apple.app`
- Linux: `gauth2apple-linux-x86_64` — `chmod +x` and run
- Windows: `gauth2apple-windows-x86_64.exe`

**Intel Mac users**: there is no prebuilt Intel binary — please use **Option B (run from source)** below. (GitHub's free-tier Intel Mac runners queue for tens of minutes per build, so we don't publish an Intel artifact. The Python script runs natively on Intel Macs.)

On macOS the binary is **unsigned**, so Gatekeeper will block it the first time. Either right-click → Open, or run once from a terminal:

```bash
xattr -d com.apple.quarantine gauth2apple.app
```

### Option B — Run from source

Requires Python 3.8+.

```bash
git clone https://github.com/itamaker/gauth2apple.git
cd gauth2apple
pip install -r requirements.txt

# zbar system library (for pyzbar):
#   macOS:   brew install zbar
#   Linux:   sudo apt-get install libzbar0 python3-tk
#   Windows: bundled inside the pyzbar wheel — nothing to install

python3 gauth2apple_gui.py
```

## Usage

1. Launch the app (binary or `python3 gauth2apple_gui.py`).
2. **macOS only**: choose whether to turn Wi-Fi off.
3. Either pick the export QR screenshot(s) or paste the `otpauth-migration://` URL.
4. A browser tab opens with one standard `otpauth://` QR per account.
5. Point the iPhone Camera at each QR → tap **"Open in Passwords"**.
6. Click **OK** in the final dialog to delete the temp page (and restore Wi-Fi if it was toggled off).

## How to get the export QR

In **Google Authenticator** on your old phone:

1. Tap the menu → **Transfer accounts** → **Export accounts**.
2. Pick the accounts to migrate (Google caps each QR at ~10 accounts; with more accounts it produces several QRs).
3. Take a screenshot of each resulting QR code.

Then feed those screenshot(s) to this tool. Multi-select is supported — select all your screenshots at once and they're merged.

## Security notes

This tool decodes high-value secrets (TOTP seeds). Treat the inputs and outputs accordingly:

- **Run it offline.** On macOS the tool can disable Wi-Fi for you; on Linux/Windows do it manually before launching.
- **Clear residual data after import.** The generated HTML page is deleted when you dismiss the final dialog, but browser cache or a screenshot can persist. Clear them.
- **Never paste a migration URL into a web tool you don't control.** That URL is *all* your 2FA secrets.
- **Verify a few codes match** between Google Authenticator and Apple Passwords before deleting the originals.
- The source is short (one Python file, no external services) — read it before running it.

## How it works (briefly)

The migration QR encodes an `otpauth-migration://offline?data=<base64>` URL. The `data` payload is a protobuf message:

```
MigrationPayload {
  repeated OtpParameters otp_parameters = 1;
  ...
}
OtpParameters {
  bytes  secret    = 1;   // raw bytes; base32 for otpauth://
  string name      = 2;
  string issuer    = 3;
  enum   algorithm = 4;   // SHA1 / SHA256 / SHA512 / MD5
  enum   digits    = 5;   // 6 / 8
  enum   type      = 6;   // TOTP / HOTP
  int64  counter   = 7;   // HOTP only
}
```

`gauth2apple_gui.py` parses that protobuf by hand (no `.proto` dependency), base32-encodes each secret, and emits one standard URL per account:

```
otpauth://totp/<issuer>:<name>?secret=<base32>&issuer=<issuer>&algorithm=SHA1&digits=6
```

That format is what Apple Passwords' "Open in Passwords" hook recognizes.

## Building releases

Releases are built by GitHub Actions on tag push. To cut a new release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/release.yml` runs PyInstaller on macOS (Apple Silicon), Linux, and Windows runners and publishes the artifacts to a new GitHub Release.

To trigger a build manually without tagging, use **Actions → Release → Run workflow** from the GitHub UI.

## File layout

```
gauth2apple_gui.py                  # Tkinter dialogs + inline browser preview
requirements.txt                    # Python dependencies
.github/workflows/release.yml       # PyInstaller cross-platform release pipeline
```

## License

MIT
