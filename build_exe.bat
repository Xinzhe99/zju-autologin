@echo off
rem 打包为单文件 exe（需要先 pip install pyinstaller）
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
    --name ZJUAutoLogin ^
    --icon resources\zju.ico ^
    --add-data "resources;resources" ^
    main.py
echo.
echo 打包完成: dist\ZJUAutoLogin.exe
pause
