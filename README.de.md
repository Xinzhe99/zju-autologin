# ZJU-AutoLogin · Automatische Anmeldung für das Campusnetz der Zhejiang-Universität

[![Tests](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml/badge.svg)](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Downloads](https://img.shields.io/github/downloads/Xinzhe99/zju-autologin/total)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Stars](https://img.shields.io/github/stars/Xinzhe99/zju-autologin?style=social)](https://github.com/Xinzhe99/zju-autologin/stargazers)
[![Issues](https://img.shields.io/github/issues/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/issues)
[![Last Commit](https://img.shields.io/github/last-commit/Xinzhe99/zju-autologin/main)](https://github.com/Xinzhe99/zju-autologin/commits)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey?logo=windows&logoColor=white)](https://github.com/Xinzhe99/zju-autologin/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | **Deutsch** | 

Ein Programm im Systemtray: **überwacht den Authentifizierungsstatus des Campusnetzwerks der Zhejiang-Universität (Srun-Portal) und meldet sich mit den gespeicherten Zugangsdaten automatisch neu an**, damit Remote-Desktop und SSH nie wegen einer abgelaufenen Sitzung abbrechen.

| Hauptfenster | Einrichtungsassistent |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## Warum

Das Campusnetz der Zhejiang-Universität nutzt das Srun-Portal mit folgendem offiziellen Hinweis:

> Aus Sicherheitsgründen ist der Zeitraum der stillen Authentifizierung auf **14 Tage** begrenzt; danach ist eine erneute Anmeldung erforderlich.

IP-Wechsel, Wiederverbindungen und Neustarts beenden die Sitzung ebenfalls. Passiert das außer Haus, ist der Fernzugriff weg. Dieses Tool automatisiert die erneute Anmeldung.

## Installation

Download von [Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) (automatisch von GitHub Actions gebaut):

| Plattform | Installer (empfohlen) | Portable |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- macOS ist unsigniert: beim ersten Start Rechtsklick → „Öffnen“
- Updates werden automatisch erkannt und mit einem Klick installiert
- Oberfläche auf Chinesisch / Englisch (folgt der Systemsprache)

## Schnellstart

1. Installieren und starten
2. Der Assistent erkennt das Netzwerk automatisch; sind Sie bereits online, wird **das Konto automatisch eingetragen** — Passwort einmal eingeben und speichern
3. Fertig: die App lebt im Tray und authentifiziert sich bei Bedarf selbst

Für Fernzugriff empfohlen: in den Einstellungen **Systemweite Aufrechterhaltung** (authentifiziert vor der Windows-Anmeldung) und **Offline-Benachrichtigungen** aktivieren.

## Funktionen

- Automatische Neuauthentifizierung mit exponentiellem Backoff, Tray-Status
- Einrichtungsassistent (Konto wird vom Portal übernommen, wenn online)
- Systemweite Aufrechterhaltung (Windows: Authentifizierung vor dem Login)
- Offline-Benachrichtigungen: Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP
- Geräteverwaltung (andere Geräte bei Erreichen des Limits abmelden)
- Ein-Klick-Update (mit SHA256-Prüfung)
- Proxy-Einstellungen, Dunkelmodus, mehrsprachige UI, CLI-Modus u. v. m.

Vollständige Dokumentation im [chinesischen README](README.md).

## Protokoll

`net.zju.edu.cn` ist ein Srun-Portal. Implementierungsdetails (Challenge / HMAC-MD5 / XXTEA / benutzerdefiniertes Base64 / SHA1) finden Sie in [zju_autologin/srun.py](zju_autologin/srun.py) und im [chinesischen README](README.md#校园网认证机制解析).

## Unterstützung

Wenn dir das Tool hilft, hinterlasse gerne einen ⭐. Bugs und Vorschläge über [Issues](https://github.com/Xinzhe99/zju-autologin/issues). PRs willkommen ([CONTRIBUTING.md](CONTRIBUTING.md)).

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

## Lizenz

[MIT](LICENSE). Das Universitätssiegel gehört der Zhejiang-Universität.
