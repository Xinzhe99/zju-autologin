@echo off
rem 本地打包为单文件 exe（需要先 pip install pyinstaller）
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name ZJUAutoLogin ^
    --icon resources\zju.ico ^
    --add-data "resources;resources" ^
    --add-data "zju_autologin\i18n;zju_autologin\i18n" ^
    --add-data "zju_autologin\portals.json;zju_autologin" ^
    --add-data "zju_autologin\webui_stat.js;zju_autologin" ^
    main.py
echo.
echo 打包完成: dist\ZJUAutoLogin.exe
echo 如需安装包, 运行: iscc installer.iss /DAppVersion=版本号
pause
