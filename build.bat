@echo off
echo ============================================================
echo Building ResourceShare.exe
echo ============================================================
echo.

pyinstaller --noconfirm ResourceShare.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] Build completed successfully!
    echo Executable: dist\ResourceShare.exe
) else (
    echo.
    echo [ERROR] PyInstaller build failed with exit code %ERRORLEVEL%.
)

echo.
pause
