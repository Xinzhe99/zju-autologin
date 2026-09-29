# ZJU-AutoLogin · 저장안대학 캠퍼스 네트워크 자동 로그인

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

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | **한국어** | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

시스템 트레이에 상주하며 저장안대학 캠퍼스 네트워크(Srun 포털) 인증 상태를 자동으로 감시하고, **오프라인 또는 만료 시 저장된 계정으로 자동 재인증**하여 원격 데스크톱·SSH 연결이 인증 만료로 끊기는 것을 방지합니다.

| 메인 화면 | 첫 실행 마법사 |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## 왜 필요한가

저장안대학 캠퍼스 네트워크는 Srun 포털 인증을 사용하며 공식 안내에 다음과 같이 명시되어 있습니다:

> 보안을 위해 무감각 인증 주기는 **14일**로 설정되어 있으며, 만료 후 재로그인이 필요합니다.

IP 변경·재접속·재부팅 시에도 인증이 만료됩니다. 외출 중 원격 연결이 끊기면 재로그인을 위해 캠퍼스로 돌아가야 합니다. 이 도구는 그 재로그인을 자동화합니다.

## 설치

[Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest)에서 다운로드(GitHub Actions 자동 빌드):

| 플랫폼 | 설치 버전(권장) | 포터블 |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- macOS 버전은 미서명이므로 최초 실행 시 우클릭 →「열기」로 허용하세요
- 업데이트는 자동 감지되며 원클릭으로 갱신할 수 있습니다
- UI는 중국어 / 영어 지원(시스템 언어 따름)

## 빠른 시작

1. 설치 후 실행
2. 첫 실행 마법사가 네트워크를 자동 감지——온라인 상태면 **계정이 자동 입력**되며, 비밀번호를 한 번 입력해 저장
3. 완료. 이후 트레이에 상주하며 오프라인 시 자동 재인증합니다

원격 사용 시「설정」에서 **시스템 수준 상주**(Windows 로그인 전 인증)와 **오프라인 알림**을 켜는 것을 권장합니다.

## 주요 기능

- 자동 재인증(지수 백오프), 트레이 상주 및 상태 표시
- 첫 실행 마법사(온라인 시 계정 자동 가져오기)
- 시스템 수준 상주(Windows: 로그인 전 인증)
- 오프라인 알림: Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP
- 기기 관리(대수 초과 시 다른 기기 강제 로그아웃)
- 원클릭 업데이트(SHA256 검증)
- 네트워크 프록시 설정, 다크 모드, 다국어 UI, CLI 모드 등

자세한 내용은 [중국어 README](README.md)를 참고하세요.

## 프로토콜

`net.zju.edu.cn`은 Srun 포털입니다. 구현 세부 사항(challenge / HMAC-MD5 / XXTEA / 커스텀 Base64 / SHA1)은 [zju_autologin/srun.py](zju_autologin/srun.py)와 [중국어 README](README.md#校园网认证机制解析)를 참고하세요.

## 지원

도움이 되었다면 ⭐ Star를 눌러주세요. 버그 보고·기능 제안은 [Issues](https://github.com/Xinzhe99/zju-autologin/issues)로, PR도 환영합니다([CONTRIBUTING.md](CONTRIBUTING.md)).

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

## 라이선스

[MIT](LICENSE). 교장 로고의 저작권은 저장안대학에 있습니다.
