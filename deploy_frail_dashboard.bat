@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo  村上市 フレイル分析ダッシュボード  Netlify 公開
echo ============================================================
echo.

set DIR=%~dp0

:: ── オプション選択 ──────────────────────────────────────────────
echo どちらの方法で公開しますか？
echo.
echo  [1] CSVアップロード型 (frail-dashboard.html をデプロイ)
echo      → URLを共有。相手がCSVをアップロードして使用。
echo.
echo  [2] データ埋め込み型 (CSVを焼き込んでデプロイ)
echo      → URLを開くだけでダッシュボードが表示。CSVは不要。
echo.
set /p CHOICE=選択 (1 or 2):

if "%CHOICE%"=="2" goto EMBED_MODE
goto UPLOAD_MODE

:: ── 埋め込みモード ──────────────────────────────────────────────
:EMBED_MODE
echo.
echo [1/3] CSVをHTMLに埋め込み中...
python "%DIR%embed_csv.py"
if errorlevel 1 (
    echo ERROR: CSV埋め込みに失敗しました
    pause
    exit /b 1
)
echo.
echo [2/3] Netlify にログイン中...
netlify login
echo.
echo [3/3] frail-dashboard-embedded.html をデプロイ中...
cd /d "%DIR%"
:: 埋め込みHTMLのみを一時フォルダにコピーしてデプロイ
if not exist "%DIR%_deploy_tmp" mkdir "%DIR%_deploy_tmp"
copy /y "%DIR%frail-dashboard-embedded.html" "%DIR%_deploy_tmp\index.html" > nul
netlify deploy --dir "%DIR%_deploy_tmp" --prod --message "フレイルダッシュボード 埋め込みデプロイ"
rmdir /s /q "%DIR%_deploy_tmp"
goto END

:: ── アップロード型モード ────────────────────────────────────────
:UPLOAD_MODE
echo.
echo [1/2] Netlify にログイン中...
netlify login
echo.
echo [2/2] frail-dashboard.html をデプロイ中...
cd /d "%DIR%"
if not exist "%DIR%_deploy_tmp" mkdir "%DIR%_deploy_tmp"
copy /y "%DIR%frail-dashboard.html" "%DIR%_deploy_tmp\index.html" > nul
netlify deploy --dir "%DIR%_deploy_tmp" --prod --message "フレイルダッシュボード デプロイ"
rmdir /s /q "%DIR%_deploy_tmp"

:END
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo  上に表示された Website URL を共有してください。
echo  このURLは永続的に有効です（Netlifyアカウントがある限り）
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
pause
