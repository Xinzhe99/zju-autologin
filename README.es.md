# ZJU-AutoLogin · Inicio de sesión automático en la red de la Universidad de Zhejiang

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

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | **Español** | [Français](README.fr.md) | [Deutsch](README.de.md)

Una app que vive en la bandeja del sistema: **vigila el estado de autenticación de la red de la Universidad de Zhejiang (portal Srun) y vuelve a autenticarse automáticamente con tus credenciales guardadas** cuando se cae o caduca, para que Escritorio Remoto o SSH nunca se pierdan por una sesión expirada.

| Ventana principal | Asistente inicial |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## Por qué

La red de la Universidad de Zhejiang usa el portal Srun, cuyo aviso oficial indica:

> Por seguridad, el periodo de autenticación silenciosa es de **14 días**; tras caducar hay que iniciar sesión de nuevo.

Cambios de IP, reconexiones y reinicios también invalidan la sesión. Si te pasa lejos del ordenador, pierdes el acceso remoto. Esta herramienta automatiza ese reinicio de sesión.

## Instalación

Descarga desde [Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) (compilado por GitHub Actions):

| Plataforma | Instalador (recomendado) | Portátil |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- macOS no está firmado: clic derecho → «Abrir» la primera vez
- Las actualizaciones se detectan automáticamente y se instalan con un clic
- Interfaz en chino / inglés (sigue el idioma del sistema)

## Inicio rápido

1. Instala y abre la app
2. El asistente detecta la red automáticamente; si ya estás conectado **rellena tu cuenta**, escribe tu contraseña una vez y guarda
3. Listo: queda en la bandeja y se re-autentica solo

Para uso remoto, activa en Ajustes la **residencia a nivel de sistema** (autentica antes del login de Windows) y las **notificaciones offline**.

## Características

- Re-autenticación automática con backoff exponencial, bandeja con estado
- Asistente inicial (obtiene la cuenta del portal si ya estás online)
- Residencia a nivel de sistema (Windows: autentica antes del login)
- Notificaciones offline: Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP
- Gestión de dispositivos (expulsa otros equipos al alcanzar el límite)
- Actualización de un clic (con verificación SHA256)
- Configuración de proxy, modo oscuro, UI multiidioma, modo CLI, etc.

Ver el [README en chino](README.md) para la documentación completa.

## Protocolo

`net.zju.edu.cn` es un portal Srun. Los detalles de implementación (challenge / HMAC-MD5 / XXTEA / Base64 personalizado / SHA1) están en [zju_autologin/srun.py](zju_autologin/srun.py) y en el [README en chino](README.md#校园网认证机制解析).

## Soporte

Si te resulta útil, deja una ⭐. Reporta bugs o propone funciones en [Issues](https://github.com/Xinzhe99/zju-autologin/issues). PRs bienvenidos ([CONTRIBUTING.md](CONTRIBUTING.md)).

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

## Licencia

[MIT](LICENSE). El sello universitario pertenece a la Universidad de Zhejiang.
