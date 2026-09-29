# ZJU-AutoLogin · 浙江大学キャンパスネットワーク自動ログイン

[![Tests](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml/badge.svg)](https://github.com/Xinzhe99/zju-autologin/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Downloads](https://img.shields.io/github/downloads/Xinzhe99/zju-autologin/total)](https://github.com/Xinzhe99/zju-autologin/releases)
[![Stars](https://img.shields.io/github/stars/Xinzhe99/zju-autologin?style=social)](https://github.com/Xinzhe99/zju-autologin/stargazers)
[![Issues](https://img.shields.io/github/issues/Xinzhe99/zju-autologin)](https://github.com/Xinzhe99/zju-autologin/issues)
[![Last Commit](https://img.shields.io/github/last-commit/Xinzhe99/zju-autologin/main)](https://github.com/Xinzhe99/zju-autologin/commits)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey?logo=apple&logoColor=white)](https://github.com/Xinzhe99/zju-autologin/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[简体中文](README.md) | [English](README.en.md) | **日本語** | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

タスクトレイに常駐し、浙江大学キャンパスネットワーク（Srun ポータル）の認証状態を自動監視。**オフラインや期限切れの際に保存されたアカウントで自動再認証**し、リモートデスクトップや SSH の接続が認証切れで切れることを防ぎます。

| メイン画面 | 初回セットアップ |
| --- | --- |
| ![Main](docs/screenshot_online.png) | ![Wizard](docs/wizard_welcome.png) |

## なぜ必要か

浙江大学のキャンパスネットワークは Srun ポータル認証を採用し、公式案内には次の記述があります：

> セキュリティのため、無感覚認証の周期は **14 日**に設定されており、期限切れ後は再ログインが必要です。

さらに IP 変化・再接続・再起動でも認証が失効します。外出中にリモート接続が切れると、再ログインするためにキャンパスへ戻らなければなりません。本ツールはその再ログインを自動化します。

## インストール

[Releases](https://github.com/Xinzhe99/zju-autologin/releases/latest) からダウンロード（GitHub Actions が自動ビルド）：

| プラットフォーム | インストーラ（推奨） | ポータブル |
| --- | --- | --- |
| Windows | `ZJUAutoLogin-*-windows-setup.exe` | `ZJUAutoLogin-*-windows-portable.zip` |
| macOS | `ZJUAutoLogin-*-macos.dmg` | `ZJUAutoLogin-*-macos-portable.zip` |

- macOS 版は未署名のため、初回起動時に右クリック →「開く」で許可してください
- アップデートは自動検出され、ワンクリックで更新できます
- UI は中国語 / 英語対応（システム言語に追従）

## クイックスタート

1. インストールして起動
2. 初回ウィザードがネットワークを自動検出——オンラインなら**アカウントを自動入力**、パスワードを 1 回入力して保存
3. 完了。以降はトレイに常駐し、オフライン時に自動再認証します

リモート利用の場合は「設定」で **システムレベル常駐**（Windows 起動直後に認証、ログイン不要）と **オフライン通知** を有効にすることを推奨します。

## 主な機能

- 自動再認証（指数バックオフ付き）、トレイ常駐・状態表示
- 初回ウィザード（オンラインならアカウントを自動取得）
- システムレベル常駐（Windows：ログイン前に認証）
- オフライン通知：Bark / ServerChan / WeCom / DingTalk / Feishu / SMTP
- デバイス管理（台数超過時に他デバイスを強制ログアウト）
- ワンクリック更新（SHA256 検証付き）
- ネットワークプロキシ設定、ダークモード、多言語 UI、CLI モード など

詳細は[中国語版 README](README.md) を参照してください。

## プロトコル

`net.zju.edu.cn` は深瀾（Srun）ポータルです。実装の詳細（challenge / HMAC-MD5 / XXTEA / カスタム Base64 / SHA1）は [zju_autologin/srun.py](zju_autologin/srun.py) および[中国語版 README](README.md#校园网认证机制解析) を参照してください。

## サポート

役に立ったら ⭐ Star をお願いします。バグ報告・機能提案は [Issues](https://github.com/Xinzhe99/zju-autologin/issues) へ。PR も歓迎です（[CONTRIBUTING.md](CONTRIBUTING.md)）。

[![Star History Chart](https://api.star-history.com/svg?repos=Xinzhe99/zju-autologin&type=Date)](https://star-history.com/#Xinzhe99/zju-autologin&Date)

## ライセンス

[MIT](LICENSE)。校章の著作権は浙江大学に帰属します。
