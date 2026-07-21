@echo off
chcp 65001 >nul 2>&1
title axios 脆弱性チェッカー

echo ===================================================
echo   axios 脆弱性チェッカー
echo   対象: axios@1.14.1, axios@0.30.4
echo   (悪意あるリモートアクセスツール入りバージョン)
echo ===================================================
echo.

set "FOUND=0"

:: npm が使えるか確認
where npm >nul 2>&1
if errorlevel 1 (
    echo [SKIP] npm が見つかりません。Node.js がインストールされていない場合、
    echo        axios の影響を受ける可能性は低いです。
    goto :RESULT
)

:: グローバルパッケージのチェック
echo --- グローバルパッケージのチェック ---
for /f "delims=" %%G in ('npm root -g 2^>nul') do set "GLOBAL_DIR=%%G"

if exist "%GLOBAL_DIR%\axios\package.json" (
    for /f "tokens=2 delims=:, " %%V in ('findstr /C:"\"version\"" "%GLOBAL_DIR%\axios\package.json"') do (
        set "VER=%%~V"
    )
    call :CHECK_VERSION "グローバル" "%VER%"
) else (
    echo [OK] グローバルに axios はインストールされていません
)

if exist "%GLOBAL_DIR%\plain-crypto-js" (
    echo [!!] 危険: グローバルに悪意ある依存関係 'plain-crypto-js' が見つかりました
    set "FOUND=1"
)
echo.

:: カレントディレクトリのチェック
echo --- カレントディレクトリのチェック ---
if exist "node_modules\axios\package.json" (
    for /f "tokens=2 delims=:, " %%V in ('findstr /C:"\"version\"" "node_modules\axios\package.json"') do (
        set "VER=%%~V"
    )
    call :CHECK_VERSION "カレントディレクトリ" "%VER%"
) else (
    echo [OK] カレントディレクトリに axios はありません
)

if exist "node_modules\plain-crypto-js" (
    echo [!!] 危険: カレントディレクトリに悪意ある依存関係 'plain-crypto-js' が見つかりました
    set "FOUND=1"
)
echo.

:: ロックファイルのチェック
echo --- ロックファイルのチェック ---
for %%L in (package-lock.json yarn.lock pnpm-lock.yaml) do (
    if exist "%%L" (
        findstr /C:"plain-crypto-js" "%%L" >nul 2>&1
        if not errorlevel 1 (
            echo [!!] 危険: %%L に 'plain-crypto-js' への参照が見つかりました
            set "FOUND=1"
        )
    )
)
echo.

:: ユーザーフォルダ配下を広くスキャン
echo --- ユーザーフォルダ配下のスキャン ---
echo     ※ 少し時間がかかる場合があります。お待ちください...
echo.

for /f "delims=" %%F in ('dir /s /b "%USERPROFILE%\node_modules\axios\package.json" 2^>nul') do (
    for /f "tokens=2 delims=:, " %%V in ('findstr /C:"\"version\"" "%%F"') do (
        set "VER=%%~V"
    )
    call :CHECK_VERSION "%%F" "%VER%"
)

for /f "delims=" %%D in ('dir /s /b /ad "%USERPROFILE%\node_modules\plain-crypto-js" 2^>nul') do (
    echo [!!] 危険: 'plain-crypto-js' が見つかりました: %%D
    set "FOUND=1"
)

goto :RESULT

:CHECK_VERSION
set "LABEL=%~1"
set "V=%~2"
:: 前後の空白と引用符を除去
set "V=%V: =%"
set "V=%V:"=%"
if "%V%"=="1.14.1" (
    echo [!!] 危険: %LABEL% に悪意あるバージョン axios@1.14.1 が見つかりました
    set "FOUND=1"
) else if "%V%"=="0.30.4" (
    echo [!!] 危険: %LABEL% に悪意あるバージョン axios@0.30.4 が見つかりました
    set "FOUND=1"
) else (
    echo [OK] %LABEL%: axios@%V% ^(安全^)
)
goto :eof

:RESULT
echo.
echo ===================================================
if "%FOUND%"=="1" (
    echo.
    echo   [!!] 悪意あるバージョンが検出されました！
    echo.
    echo   エンジニアの方に以下を伝えてください:
    echo     - axios@1.14.1 または axios@0.30.4 が検出された
    echo     - plain-crypto-js というパッケージが見つかった
    echo     - PCがマルウェアに感染している可能性がある
    echo.
    echo   すぐにネットワークから切断し、情報セキュリティ担当に連絡してください。
    echo.
) else (
    echo.
    echo   [OK] 問題は検出されませんでした。安全です。
    echo.
)
echo ===================================================
echo.
echo 何かキーを押すと閉じます...
pause >nul
