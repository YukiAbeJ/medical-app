"""
外部公開用サーバー＋トンネル起動スクリプト
ngrokのHTTPSトンネル経由で、WiFi不要でスマホ・別PCからアクセス可能。
カメラ・マイクもngrokのHTTPS経由なら動作する。
"""
import http.server
import threading
import os
import time

# ファイルの場所に移動
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ローカルHTTPサーバー（ngrokがHTTPS化してくれる）
HTTP_PORT = 8080

def start_http():
    server = http.server.HTTPServer(('127.0.0.1', HTTP_PORT), http.server.SimpleHTTPRequestHandler)
    server.serve_forever()

print("=" * 55)
print("  外部公開サーバー起動中...")
print("=" * 55)

# HTTPサーバーをバックグラウンドで起動
t = threading.Thread(target=start_http, daemon=True)
t.start()
print(f"  ローカルHTTPサーバー起動 (port {HTTP_PORT})")

# ngrokトンネル
try:
    from pyngrok import ngrok
    tunnel = ngrok.connect(HTTP_PORT, "http")
    public_url = tunnel.public_url
    # httpsに統一
    if public_url.startswith("http://"):
        public_url = public_url.replace("http://", "https://", 1)

    app_url = f"{public_url}/ai-cohort-dashboard.html"

    print()
    print(f"  ===================================")
    print(f"  スタッフ共有URL:")
    print(f"  {app_url}")
    print(f"  ===================================")
    print()
    print("  使い方:")
    print("  1. 上記URLをスタッフのスマホに共有")
    print("  2. 初回アクセス時「Visit Site」をタップ")
    print("  3. カメラ・マイクはHTTPS経由で動作します")
    print()
    print("  Ctrl+C で停止")
    print("=" * 55)

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\n停止しています...")
    ngrok.kill()
    print("停止しました。")
except Exception as e:
    print(f"\nngrokエラー: {e}")
    print()
    print("初回セットアップ手順:")
    print("  1. https://ngrok.com で無料アカウント作成")
    print("  2. ダッシュボード > Your Authtoken をコピー")
    print("  3. 以下を実行:")
    print('     python -c "from pyngrok import ngrok; ngrok.set_auth_token(\'ここにトークン\')"')
    print("  4. 再度このスクリプトを実行")
