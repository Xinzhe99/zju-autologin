# ZJU-AutoLogin · Connexion automatique au réseau de l'Université du Zhejiang

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

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | **Français** | [Deutsch](README.de.md)

Une application qui réside dans la barre des tâches : **surveille l'authentification du réseau de l'Université du Zhejiang (portail Srun) et se ré-authentifie automatiquement** en cas de coupure ou d'expiration, pour que Bureau à distance et SSH ne tombent jamais à cause d'une session expirée.

| Fenêtre principale | Assistant initial |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## Pourquoi

Le réseau de l'Université du Zhejiang utilise le portail Srun, dont l'avis officiel indique :

> Pour votre sécurité, la période d'authentification silencieuse est de **14 jours** ; une nouvelle connexion est requise après expiration.

Les changements d'IP, reconnexions et redémarrages invalident aussi la session. Si cela arrive loin de l'ordinateur, l'accès distant est perdu. Cet outil automatise cette reconnexion.

## Installation

Téléchargez depuis [Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) (compilé par GitHub Actions) :

| Plateforme | Installateur (recommandé) | Portable |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- macOS non signé : clic droit → « Ouvrir » au premier lancement
- Les mises à jour sont détectées automatiquement et installables en un clic
- Interface en chinois / anglais (suit la langue du système)

## Démarrage rapide

1. Installez et ouvrez l'application
2. L'assistant détecte le réseau automatiquement ; si vous êtes déjà connecté, **votre compte est pré-rempli** — saisissez le mot de passe une fois et enregistrez
3. C'est tout : l'app reste dans la zone de notification et se ré-authentique seule

Pour un usage à distance, activez dans les réglages la **résidence au niveau système** (authentifie avant l'ouverture de session Windows) et les **notifications hors ligne**.

## Fonctionnalités

- Ré-authentification automatique avec backoff exponentiel, icône tray avec état
- Assistant initial (récupère le compte depuis le portail si déjà en ligne)
- Résidence au niveau système (Windows : authentifie avant le login)
- Notifications hors ligne : Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP
- Gestion des appareils (déconnecte les autres en cas de limite atteinte)
- Mise à jour en un clic (avec vérification SHA256)
- Configuration proxy, mode sombre, UI multilingue, mode CLI, etc.

Voir le [README en chinois](README.md) pour la documentation complète.

## Protocole

`net.zju.edu.cn` est un portail Srun. Les détails d'implémentation (challenge / HMAC-MD5 / XXTEA / Base64 personnalisé / SHA1) sont dans [zju_autologin/srun.py](zju_autologin/srun.py) et le [README en chinois](README.md#校园网认证机制解析).

## Soutenir

Si cet outil vous a été utile, laissez une ⭐. Bugs et suggestions via [Issues](https://github.com/Xinzhe99/zju-autologin/issues). PR bienvenues ([CONTRIBUTING.md](CONTRIBUTING.md)).

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

## Licence

[MIT](LICENSE). Le sceau universitaire appartient à l'Université du Zhejiang.
