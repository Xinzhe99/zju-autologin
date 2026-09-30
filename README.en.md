# ZJU-AutoLogin · Campus Network Auto-Login (Srun)

[![Tests](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml/badge.svg)](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Downloads](https://img.shields.io/github/downloads/Xinzhe99/zju-autologin/total)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Stars](https://img.shields.io/github/stars/Xinzhe99/zju-autologin?style=social)](https://github.com/Xinzhe99/zju-autologin/stargazers)
[![Issues](https://img.shields.io/github/issues/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/issues)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Win%20%7C%20macOS%20%7C%20Linux-lightgrey?logo=linux&logoColor=white)](https://github.com/Xinzhe99/zju-autologin/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[简体中文](README.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

A tray application that runs in the background: it **watches the campus network (Srun portal) authentication state and re-authenticates automatically with your saved credentials** whenever it drops or expires — so Remote Desktop / SSH sessions never die because of an expired captive-portal login. Works at any Srun university; Zhejiang University is the founding verified school.

| Main window | First-run wizard |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## Why

Campus portals (Srun) enforce a **mandatory manual re-login every 14 days** even with silent auth (MacAuth) enabled, and IP changes / reconnects / reboots drop the session too. If that happens while you are away, your remote connection is gone. This tool logs back in for you before you even notice.

## Install

Grab a package from [Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) (built by GitHub Actions):

| Platform | Installer | Portable |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| Windows, keep-alive only (8 MB) | — | `zju-autologin-windows-cli.exe` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |
| Linux / router | — | `zju-autologin-linux-x86_64` / `-aarch64` / `-musl` |

Linux one-liner (systemd service, root:600 credentials, starts immediately):

```bash
pip install zju-autologin
sudo zju-autologin enable -u STUDENT_ID --pass-stdin <<< 'PASSWORD'
```

> macOS builds are unsigned — right-click the app → **Open**, or run `xattr -cr /Applications/ZJU\ AutoLogin.app`.

## Quick start

1. **Install** the setup package (or unzip the portable one and run `ZJUAutoLogin.exe`)
2. **First-run wizard** — it detects your network; if you are already online your account is filled in automatically. Confirm it, enter your campus password once, tick "Launch at startup", done
3. **That's it** — the app lives in the tray and re-authenticates before you even notice a drop

Recommended for remote access: enable **System-level keep-alive** in Settings (authenticates before Windows login), and configure **offline notifications** so your phone knows if anything needs manual attention.

## Features

- **First-run wizard** — detects the network automatically; if already online, your account is filled in from the portal (the password can never be captured — you type it once)
- **Keep-alive** — configurable interval (default 60 s); auto re-login with exponential backoff; **event-driven re-check within 2 s** on Wi-Fi/cable/VPN changes
- **System-level keep-alive** — Windows SYSTEM scheduled task / macOS LaunchDaemon / Linux systemd: authenticates **before anyone logs in**, survives reboots and power cuts
- **Captcha support** — a dialog pops up with the image when your school enables login captcha; type it and login completes
- **Offline push notifications** — Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP email; recovery notice included ([setup guide](docs/notifications.md))
- **Heartbeat (dead man's switch)** — ping a healthchecks.io URL every 5 minutes; the external service alerts you when the machine goes completely silent
- **Device manager & auto-kick** — list online devices when the E2620 limit is hit, kick the oldest with one click (local device protected); optional automatic kick
- **Diagnostics** — one-click `zju-autologin diagnose`, outage replay timeline, copy-to-clipboard diagnostics, rolling `app.log`
- **DNS-failure fallback** — connects via cached portal IP when campus DNS is down; **VPN bypass** (direct + NIC binding + optional admin route)
- **Self-update** — pre-downloaded, SHA256-verified, in-place swap and restart (no installer needed)
- **Tiny headless footprint** — 8 MB CLI binary for Windows/servers; web config page (`zju-autologin serve`, localhost only) for NAS/Raspberry Pi
- **i18n** — 简体中文 / English, follows the system language; dark mode follows the system
- CLI: `check | login | watch | enable | disable | status | diagnose | serve`

The full protocol spec (challenge / XXTEA / custom Base64 / SHA1) reusable for any Srun campus in any language: **[docs/srun-protocol.md](docs/srun-protocol.md)**. School compatibility matrix and the community portal list: [portals.json](zju_autologin/portals.json) — one-line PR adds your university.

## Support & Contributing

If this tool saved you from a dead remote session, consider leaving a ⭐ — it helps more students find it:

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

- 🐛 Found a bug? Open an [Issue](https://github.com/Xinzhe99/zju-autologin/issues) — attach the output of "Copy diagnostics"
- 💡 Feature ideas are welcome via Issues
- 🔧 PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) (includes how to add a new language or a new university)

## License

[MIT](LICENSE). The university seal belongs to Zhejiang University and is only used as the founding-school identifier.
