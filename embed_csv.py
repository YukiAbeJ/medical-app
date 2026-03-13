#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_csv.py
CSV データを frail-dashboard.html に埋め込んで自己完結型HTMLを生成するスクリプト。
生成された HTML はブラウザで開くだけでダッシュボードが表示されます。

使い方:
  python embed_csv.py                        # ClaudeProject内のCSVを自動検出
  python embed_csv.py ファイル1.csv ファイル2.csv   # ファイルを指定
"""
import os, sys, re, io, json, glob, datetime
import pandas as pd

# ───────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'frail-dashboard.html')
OUTPUT   = os.path.join(HERE, 'frail-dashboard-embedded.html')

BLACKLIST_KW = ['フォローアップリスト', '高リスク対象者リスト', 'follow_up_list', '集計表',
                'embedded', 'dashboard']

# ───────────────────────────────────────────
def find_csvs():
    """引数指定なし: ClaudeProject内のCSVを自動検出（ブラックリスト除外）"""
    files = []
    for f in glob.glob(os.path.join(HERE, '*.csv')):
        name = os.path.basename(f)
        if not any(k in name for k in BLACKLIST_KW):
            files.append(f)
    return sorted(files)

def read_csv_safe(path):
    for enc in ['utf-8-sig', 'cp932', 'utf-8']:
        try:
            df = pd.read_csv(path, encoding=enc, low_memory=False)
            # Unnamed列を除去
            df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]
            if len(df) > 0:
                return df
        except Exception:
            continue
    return None

def normalize_id(df):
    """ID列を探して整数型'ID'に正規化"""
    import numpy as np
    cands = [c for c in df.columns if re.search(r'\bID\b|^ID_|_ID$', str(c), re.IGNORECASE)
             or str(c).strip().lower() == 'id']
    if not cands:
        cands = [c for c in df.columns if re.search(r'\.\s*ID\s*$', str(c), re.IGNORECASE)]
    if not cands:
        return None
    ic = cands[0]
    df = df.copy()
    df[ic] = (df[ic].astype(str).str.strip()
                    .str.replace(r'^0+', '', regex=True)
                    .replace('', float('nan')))
    df[ic] = pd.to_numeric(df[ic], errors='coerce')
    df = df.dropna(subset=[ic]).copy()
    df[ic] = df[ic].astype(int)
    return df.rename(columns={ic: 'ID'}) if ic != 'ID' else df

def merge_csvs(paths):
    """複数CSVをIDキーでLEFT JOIN"""
    raw = {}
    info = []
    for path in paths:
        name = os.path.basename(path)
        df = read_csv_safe(path)
        if df is None:
            info.append(f'  SKIP {name}: 読み込みエラー')
            continue
        df2 = normalize_id(df)
        if df2 is None:
            info.append(f'  SKIP {name}: ID列なし')
            continue
        df2 = df2.drop_duplicates(subset=['ID'], keep='first')
        raw[name] = df2
        info.append(f'  OK   {name}: {len(df2)}名 / {len(df2.columns)}列')

    if not raw:
        return None, info

    # マスター選定（性別・年齢含む or 行数が多い）
    def score(name, df):
        s = len(df) + len(df.columns) * 2
        if any('性別' in c for c in df.columns): s += 200
        if any('年齢' in c for c in df.columns): s += 200
        if any(k in name for k in ['マスター', 'master', 'Master']): s += 100000
        return s

    master_name = max(raw, key=lambda n: score(n, raw[n]))
    merged = raw[master_name].copy()

    for name, df in raw.items():
        if name == master_name:
            continue
        dup = {c: f'{c}__x' for c in df.columns if c != 'ID' and c in merged.columns}
        df = df.rename(columns=dup)
        merged = merged.merge(df, on='ID', how='left')

    merged = merged.loc[:, ~merged.columns.duplicated(keep='first')]

    # NaN→None（JSON serializable）
    merged = merged.where(pd.notnull(merged), None)
    return merged, info

def df_to_json(df):
    """DataFrameをJSON文字列に変換（数値はfloat/int、文字列はstr）"""
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col, val in row.items():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                rec[col] = None
            elif isinstance(val, (int, float)):
                rec[col] = val
            else:
                rec[col] = str(val)
        records.append(rec)
    return json.dumps(records, ensure_ascii=False)

# ───────────────────────────────────────────
def main():
    print('=' * 55)
    print(' フレイルダッシュボード CSV埋め込みツール')
    print('=' * 55)

    # ファイル収集
    if len(sys.argv) > 1:
        paths = [os.path.abspath(p) for p in sys.argv[1:] if p.lower().endswith('.csv')]
        if not paths:
            print('ERROR: .csvファイルを指定してください')
            sys.exit(1)
    else:
        paths = find_csvs()
        if not paths:
            print('ERROR: ClaudeProjectフォルダにCSVファイルが見つかりません')
            sys.exit(1)

    print(f'\n対象ファイル ({len(paths)}件):')
    for p in paths:
        print(f'  {os.path.basename(p)}')

    # マージ
    print('\nCSVを結合中...')
    merged, info = merge_csvs(paths)
    for line in info:
        print(line)

    if merged is None:
        print('\nERROR: 有効なデータが読み込めませんでした')
        sys.exit(1)

    print(f'\n統合結果: {len(merged)}名 / {len(merged.columns)}列')

    # HTMLテンプレート読み込み
    if not os.path.exists(TEMPLATE):
        print(f'\nERROR: {TEMPLATE} が見つかりません')
        sys.exit(1)

    with open(TEMPLATE, 'r', encoding='utf-8') as f:
        html = f.read()

    # データをJSON化してHTMLに埋め込む
    data_json = df_to_json(merged)
    file_list = json.dumps([os.path.basename(p) for p in paths], ensure_ascii=False)
    build_ts   = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 最後の </script> タグの直前に注入（rfind で位置を特定 → 改行コード差異に依存しない）
    # NOTE: スクリプトはbody末尾にあるため DOMContentLoaded は既に発火済み。
    #       直接呼び出し方式で確実に実行する。
    INJECT = f"""
// ══ 埋め込みデータ ══
(function() {{
  window.__EMBEDDED__ = {{
    data:  {data_json},
    files: {file_list},
    ts:    "{build_ts}"
  }};
}})();

// ══ 埋め込みデータ自動ロード（DOM構築済みのため直接実行）══
(function runEmbedded() {{
  var e = window.__EMBEDDED__;
  if (!e) return;

  // バナー表示
  var banner = document.createElement('div');
  banner.style.cssText = 'background:#065f46;color:white;text-align:center;padding:6px 12px;font-size:12px;font-weight:600;letter-spacing:.03em;position:relative;z-index:100;';
  banner.textContent = '\U0001F4E6 \u57cb\u3081\u8FBC\u307f\u30C7\u30FC\u30BF\u30E2\u30FC\u30C9 \u2014 ' + e.files.join(', ') + '  (' + e.ts + ' \u751F\u6210)';
  document.body.insertBefore(banner, document.body.firstChild);

  // 処理パイプライン（frail-dashboard.htmlのprocessRows()を使用）
  loadedFiles = e.files;
  var processed = processRows(e.data);
  initDashboard(processed);
}})();
"""
    last_script_close = html.rfind('</script>')
    if last_script_close == -1:
        raise ValueError('</script> タグが見つかりません')
    html = html[:last_script_close] + INJECT + html[last_script_close:]

    # 出力
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f'\n生成完了: {os.path.basename(OUTPUT)}')
    print(f'ファイルサイズ: {size_kb:.1f} KB')
    print(f'\nこのHTMLファイルをブラウザで開くだけでダッシュボードが表示されます。')
    print(f'Netlifyやメール添付でも配布可能です。')
    print(f'\n出力先: {OUTPUT}')

if __name__ == '__main__':
    main()
