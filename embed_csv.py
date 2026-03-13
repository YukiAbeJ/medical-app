#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_csv.py
CSV データを frail-dashboard.html に埋め込んで自己完結型HTMLを生成するスクリプト。
生成された HTML はブラウザで開くだけでダッシュボードが表示されます。

使い方:
  python embed_csv.py                        # ClaudeProject + Downloadsを自動検出
  python embed_csv.py ファイル1.csv ファイル2.csv   # ファイルを指定
"""
import os, sys, re, io, json, glob, datetime
import pandas as pd

# ───────────────────────────────────────────
HERE     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'frail-dashboard.html')
OUTPUT   = os.path.join(HERE, 'frail-dashboard-embedded.html')

# 検索ディレクトリ（HERE優先、次にDownloads）
SEARCH_DIRS = [
    HERE,
    os.path.join(os.path.expanduser('~'), 'Downloads'),
]

# 分析対象外ファイルキーワード
BLACKLIST_KW = [
    'フォローアップリスト', '高リスク対象者リスト', 'follow_up_list',
    '集計表', 'embedded', 'dashboard', '評価結果', '評価用紙',
    'Inbody',     # SMIはマスターに収録済み。196列の巨大CSVを除外
    '呼吸器筋',   # ダッシュボード未使用指標
]

# J-CHS 5項目の列名（実データCSVの列名に合わせる）
FRAIL_ITEM_COLS = [
    '軽い運動plus定期的運動_0_1',     # 低活動（0=非活動=フレイル点）
    '6ヵ月体重減少_0_1',              # 体重減少
    '訳もなく疲れたように感じる_0_1',  # 疲労感
    '4m歩行_1_0_値',                  # 歩行速度低下（1=低速=フレイル点）
    '握力_0_1_値',                    # 握力低下（1=低下=フレイル点）
]

# オーラルフレイル列名マッピング（実CSV列名 → ダッシュボード列名）
ORAL_COL_MAP = {
    'オーラルフレイル_総合点': 'オーラルフレイル_判定_',
    'オーラルフレイル_判定':   'オーラルフレイル_判定_',
}

# ───────────────────────────────────────────
def find_csvs():
    """引数指定なし: SEARCH_DIRS内のCSVを自動検出（ブラックリスト除外・重複除外）"""
    files = []
    seen_names = set()
    for d in SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for f in sorted(glob.glob(os.path.join(d, '*.csv'))):
            name = os.path.basename(f)
            if name in seen_names:
                continue  # 同名ファイルは先に見つかったもの優先
            if any(k in name for k in BLACKLIST_KW):
                continue
            seen_names.add(name)
            files.append(f)
    return files


def read_csv_safe(path):
    """エンコード自動判定・マルチラインヘッダー対応の CSV 読み込み"""
    for enc in ['utf-8-sig', 'cp932', 'utf-8']:
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, low_memory=False)

            # 列名正規化: 改行 → _ （マルチラインヘッダー対応）
            def clean_col(c):
                parts = [p.strip() for p in str(c).split('\n') if p.strip()]
                return '_'.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else str(c))
            df.columns = [clean_col(c) for c in df.columns]

            # Unnamed列除去
            df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]

            # 85%以上が数字列名 → 先頭行がタイトル行 → header=1 で再読み込み
            non_un = [c for c in df.columns if not str(c).startswith('Unnamed:')]
            if non_un and (
                sum(bool(re.match(r'^[\d\s.]+$', str(c).strip())) for c in non_un) / len(non_un) > 0.85
            ):
                df = pd.read_csv(io.BytesIO(raw), encoding=enc, header=1, low_memory=False)
                df.columns = [clean_col(c) for c in df.columns]
                df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]

            # 重複列名除去
            df = df.loc[:, ~df.columns.duplicated(keep='first')]

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

    # マスター選定（マスター名優先、次に性別・年齢含む行数の多いファイル）
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


def postprocess(merged):
    """マージ後の後処理: オーラルフレイル列リネーム + 簡易フレイルスコア計算"""
    print('\n後処理中...')

    # 1. オーラルフレイル列名を統一
    for src, dst in ORAL_COL_MAP.items():
        if src in merged.columns and dst not in merged.columns:
            merged = merged.rename(columns={src: dst})
            print(f'  → {src} → {dst} にリネーム')

    # 2. 簡易フレイルスコア (J-CHS 5項目) を計算
    #    ※各項目: 1=フレイル点, 0=正常（活動のみ0=低活動=フレイル点）
    if '簡易フレイルスコア' not in merged.columns:
        avail = [c for c in FRAIL_ITEM_COLS if c in merged.columns]
        if len(avail) >= 3:
            for col in avail:
                merged[col] = pd.to_numeric(merged[col], errors='coerce')

            # 活動列は 0=低活動=フレイル点 なので反転して加算
            activity_col = '軽い運動plus定期的運動_0_1'
            scores = pd.Series(0.0, index=merged.index)
            counted = pd.Series(0, index=merged.index)
            for col in avail:
                v = pd.to_numeric(merged[col], errors='coerce')
                has_val = v.notna()
                counted += has_val.astype(int)
                if col == activity_col:
                    scores += (v == 0).astype(float).where(has_val, 0.0)
                else:
                    scores += (v >= 1).astype(float).where(has_val, 0.0)

            valid_mask = counted >= 3
            merged['簡易フレイルスコア'] = scores.where(valid_mask)

            valid_n = merged['簡易フレイルスコア'].notna().sum()
            risk_n  = (merged['簡易フレイルスコア'] >= 3).sum()
            pref_n  = ((merged['簡易フレイルスコア'] >= 1) & (merged['簡易フレイルスコア'] < 3)).sum()
            print(f'  → 簡易フレイルスコア計算 ({len(avail)}/5項目使用): {avail}')
            print(f'     フレイル(>=3): {risk_n}/{valid_n}名 = {risk_n/valid_n*100:.1f}%')
            print(f'     プレフレイル(1-2): {pref_n}/{valid_n}名 = {pref_n/valid_n*100:.1f}%')
        else:
            print(f'  ※ フレイル項目列が不足のためスキップ: 検出{len(avail)}/5 {avail}')
    else:
        valid_n = merged['簡易フレイルスコア'].notna().sum()
        print(f'  ※ 簡易フレイルスコア: 既存列を使用 ({valid_n}名有効)')

    # 後処理後の重複列除去
    merged = merged.loc[:, ~merged.columns.duplicated(keep='first')]
    return merged


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
            print('ERROR: CSVファイルが見つかりません (ClaudeProject / Downloads を確認してください)')
            sys.exit(1)

    print(f'\n対象ファイル ({len(paths)}件):')
    for p in paths:
        print(f'  [{os.path.dirname(p).split(os.sep)[-1]}] {os.path.basename(p)}')

    # マージ
    print('\nCSVを結合中...')
    merged, info = merge_csvs(paths)
    for line in info:
        print(line)

    if merged is None:
        print('\nERROR: 有効なデータが読み込めませんでした')
        sys.exit(1)

    print(f'\n統合結果: {len(merged)}名 / {len(merged.columns)}列')

    # 後処理（派生列計算）
    merged = postprocess(merged)

    # HTMLテンプレート読み込み
    if not os.path.exists(TEMPLATE):
        print(f'\nERROR: {TEMPLATE} が見つかりません')
        sys.exit(1)

    with open(TEMPLATE, 'r', encoding='utf-8') as f:
        html = f.read()

    # データをJSON化してHTMLに埋め込む
    data_json  = df_to_json(merged)
    file_list  = json.dumps([os.path.basename(p) for p in paths], ensure_ascii=False)
    build_ts   = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 最後の </script> タグの直前に注入
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
    print(f'\n出力先: {OUTPUT}')


if __name__ == '__main__':
    main()
