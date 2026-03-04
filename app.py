#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
村上市 自治体向け総合フレイル分析ダッシュボード v3
AWGS2019 / J-CHS / WHO 基準準拠
"""

# ─── 0. 自動インストール ──────────────────────────────────────────────────────
import subprocess, sys, importlib

def _ensure(*pkgs):
    for pkg in pkgs:
        mod = pkg.split('[')[0].replace('-', '_')
        try:
            importlib.import_module(mod)
        except ImportError:
            try:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass  # requirements.txt で管理されている場合はスキップ

_ensure('pandas', 'streamlit', 'plotly', 'numpy')

# ─── 1. インポート ───────────────────────────────────────────────────────────
import os, io, re
import glob as _glob
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go

# ─── 2. 定数 ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SEARCH_DIRS = [
    _HERE,
    os.path.join(os.path.expanduser('~'), 'Downloads'),
    os.path.join(os.path.expanduser('~'), 'Desktop'),
]

AGE_BINS   = [0, 64, 69, 74, 79, 200]
AGE_LABELS = ['65歳未満', '65-69歳', '70-74歳', '75-79歳', '80歳以上']

CUTOFFS: Dict = {
    '歩行速度低下':      {'col': '歩行速度_mps',      'op': '<',   'val': 1.0,
                         'icon': '🚶', 'color': '#DC2626',
                         'basis': 'AWGS2019: 通常歩行速度 < 1.0 m/s'},
    '下肢筋力低下':      {'col': '5回立ち上がり_秒',   'op': '>=',  'val': 12.0,
                         'icon': '🦵', 'color': '#EA580C',
                         'basis': 'SPPB準拠: 5回椅子立ち上がり ≥ 12秒'},
    'サルコペニア疑い':   {'col': 'SMI',              'op': 'sex', 'val': (7.0, 5.7),
                         'icon': '💪', 'color': '#D97706',
                         'basis': 'AWGS2019: SMI < 7.0（男）/ < 5.7（女）kg/m²'},
    '骨密度低下':        {'col': 'Tスコア_SD',         'op': '<=',  'val': -1.0,
                         'icon': '🦴', 'color': '#CA8A04',
                         'basis': 'WHO基準: Tスコア ≤ −1.0 SD（骨減少症以上）'},
    'MCI疑い':           {'col': 'MoCA総得点',         'op': '<=',  'val': 25,
                         'icon': '🧠', 'color': '#7C3AED',
                         'basis': 'Nasreddine 2005: MoCA ≤ 25点'},
    '嚥下機能低下リスク': {'col': 'EAT10総得点',        'op': '>=',  'val': 3,
                         'icon': '🍽', 'color': '#0284C7',
                         'basis': 'Belafsky 2008: EAT-10 ≥ 3点'},
}

FUTURE_INDICATORS: Dict = {
    'フレイル判定':    {'col': '簡易フレイルスコア',       'icon': '🩺', 'color': '#B91C1C',
                       'basis': '簡易フレイルインデックス(5項目合計): ≥3でフレイル, 1-2でプレフレイル',
                       'val': 3, 'op': '>='},
    'オーラルフレイル': {'col': 'オーラルフレイル_判定_',  'icon': '👄', 'color': '#0891B2',
                       'basis': '口腔機能質問紙（咀嚼・ディアドコ等）: 判定あり（1以上）で該当',
                       'val': 1, 'op': '>='},
    'バランス能力低下': {'col': 'バランス_得点',           'icon': '⚖️',  'color': '#059669',
                       'basis': 'SPPB バランス検査: 4点未満',
                       'val': 4, 'op': '<'},
    'サルコペニア確定': {'col': None,                     'icon': '✊', 'color': '#9333EA',
                       'basis': 'AWGS2019: 低SMI ＋ 歩行速度低下または椅子立ち上がり低下',
                       'val': None, 'op': None},
}

# KPIカード表示順序（ユーザー指定）
DISPLAY_ORDER = [
    'フレイル判定', '下肢筋力低下', '歩行速度低下', 'バランス能力低下',
    'サルコペニア疑い', 'オーラルフレイル', 'MCI疑い', '嚥下機能低下リスク',
    '骨密度低下', 'サルコペニア確定',
]

P = {
    'navy':   '#0F2044',           # ディープネイビー（HAL Lab ブランド）
    'blue':   '#1A5FB4',           # コーポレートブルー
    'sky':    '#3B9FE8',           # スカイブルー
    'accent': '#F97316',           # HAL Lab オレンジ（ブランドアクセント）
    'red':    '#B83658',           # リスク赤（ダスティローズレッド）
    'orange': '#EA580C',           # 警告オレンジ
    'green':  '#16A34A',           # 安全グリーン
    'amber':  '#B45309',           # アンバー
    'violet': '#6D28D9',           # バイオレット
    'cyan':   '#0369A1',           # シアン
    'text':   '#1E2D40',           # ボディテキスト
    'muted':  '#526070',           # ミュートテキスト
    'border': 'rgba(180,200,220,.55)',  # ガラス境界線
    'bg':     '#E8EFF7',           # ページ背景（ソフトブルーグレー）
    'card':   'rgba(255,255,255,0.88)', # ガラスカード
    'glass':  'rgba(255,255,255,0.72)', # より透明なガラス
}


# ─── 2b. HAL Lab ロゴ読み込み ────────────────────────────────────────────────
def _load_logo_b64() -> str:
    """hal_logo_b64.txt からロゴのbase64文字列を読み込む"""
    _lp = os.path.join(_HERE, 'hal_logo_b64.txt')
    try:
        with open(_lp, 'r') as _lf:
            return _lf.read().strip()
    except Exception:
        return ''

_HAL_LOGO_B64: str = _load_logo_b64()


# ─── 3. データ処理 ────────────────────────────────────────────────────────────
def _read_csv_safe(path: str) -> Optional[pd.DataFrame]:
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        enc = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'cp932'
        df = pd.read_csv(io.BytesIO(raw), encoding=enc, low_memory=False)
        # 数字見出し行検出（先頭行が 1,2,3... → 実ヘッダーは行1）
        # Unnamed列・重複連番 "18 .1" 形式も除外し、85%以上が数字列なら再読み込み
        _non_unnamed = [c for c in df.columns
                        if not str(c).startswith('Unnamed:')]
        _is_num_col  = lambda c: bool(re.match(r'^[\d\s.]+$', str(c).strip()))
        if (len(_non_unnamed) > 1 and
                sum(_is_num_col(c) for c in _non_unnamed) / len(_non_unnamed) > 0.85):
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, header=1, low_memory=False)
        # 複数行列名（\n含む）を「パート1_パート2」形式に正規化
        def _clean_col(c: str) -> str:
            parts = [p.strip() for p in str(c).split('\n') if p.strip()]
            return '_'.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else str(c))
        df.columns = [_clean_col(c) for c in df.columns]
        # 正規化後に重複した列名を除去（最初の出現を保持）
        df = df.loc[:, ~df.columns.duplicated(keep='first')]
        return df
    except Exception:
        return None


def _normalize_id_col(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """ID列を探して整数型 'ID' に正規化する。"""
    cands = [c for c in df.columns
             if re.search(r'\bID\b|^ID_|_ID$', str(c), re.IGNORECASE)]
    if not cands:
        cands = [c for c in df.columns if str(c).strip().lower() == 'id']
    if not cands:
        # "2.ID" 形式（Inbodyエクスポート等、数字プレフィックス付き）
        cands = [c for c in df.columns
                 if re.search(r'\.\s*ID\s*$', str(c), re.IGNORECASE)]
    if not cands:
        return None
    ic = cands[0]
    df = df.copy()
    df[ic] = (df[ic].astype(str).str.strip()
                    .str.replace(r'^0+', '', regex=True)
                    .replace('', np.nan))
    df[ic] = pd.to_numeric(df[ic], errors='coerce')
    df = df.dropna(subset=[ic]).copy()
    df[ic] = df[ic].astype(int)
    return df.rename(columns={ic: 'ID'}) if ic != 'ID' else df


def _is_skip_file(df: Optional[pd.DataFrame]) -> bool:
    """デバイスエクスポートや集計表など結合不適ファイルを検出する。"""
    if df is None or df.empty:
        return True
    cols = [str(c) for c in df.columns]
    if any(kw in c for c in cols[:3] for kw in ['氏名', '測定日時', '測定日']):
        return True
    if cols[0] in ('指標', '項目', '集計'):
        return True
    if len(df) < 3:
        return True
    return False


@st.cache_data(show_spinner='全CSVデータを統合中...')
def load_merged(uploaded_files: Optional[tuple] = None) -> Tuple[pd.DataFrame, List[str], List[dict]]:
    # ── ファイル収集（重複除外）──
    path_map: Dict[str, str] = {}
    for d in _SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except Exception:
            continue
        for fname in entries:
            if fname.lower().endswith('.csv') and fname not in path_map:
                path_map[fname] = os.path.join(d, fname)

    raw_dfs: Dict[str, pd.DataFrame] = {}
    _warn: List[dict] = []

    for fname, path in path_map.items():
        df = _read_csv_safe(path)
        if _is_skip_file(df):
            continue
        df = _normalize_id_col(df)
        if df is None:
            continue
        for c in df.columns:
            if c != 'ID':
                df[c] = pd.to_numeric(df[c], errors='coerce')
        raw_dfs[fname] = df

    for _uidx, _ubytes in enumerate(uploaded_files or []):
        _label = f'ファイル #{_uidx + 1}'
        enc = 'utf-8-sig' if _ubytes.startswith(b'\xef\xbb\xbf') else 'cp932'
        try:
            df = pd.read_csv(io.BytesIO(_ubytes), encoding=enc, low_memory=False)
            _orig_cols = list(df.columns)
            _orig_rows = len(df)
            if _is_skip_file(df):
                _warn.append({'file': _label, 'status': 'skip',
                              'reason': 'スキップ（氏名・測定日列あり or 行数3未満）',
                              'cols': _orig_cols, 'rows': _orig_rows, 'id_col': None})
            else:
                df2 = _normalize_id_col(df)
                if df2 is None:
                    _warn.append({'file': _label, 'status': 'no_id',
                                  'reason': 'ID列が見つかりません。列名にID・id・ID_xxxが必要です。',
                                  'cols': _orig_cols, 'rows': _orig_rows, 'id_col': None})
                else:
                    _id_col_orig = next((c for c in _orig_cols
                                         if re.search(r'\bID\b|^ID_|_ID$', str(c), re.IGNORECASE)
                                         or str(c).strip().lower() == 'id'), _orig_cols[0])
                    for c in df2.columns:
                        if c != 'ID':
                            df2[c] = pd.to_numeric(df2[c], errors='coerce')
                    raw_dfs[f'__upload_{_uidx}__'] = df2
                    _warn.append({'file': _label, 'status': 'ok',
                                  'reason': 'OK',
                                  'cols': list(df2.columns), 'rows': len(df2),
                                  'id_col': _id_col_orig})
        except Exception as _e:
            _warn.append({'file': _label, 'status': 'error',
                          'reason': f'読み込みエラー: {_e}',
                          'cols': [], 'rows': 0, 'id_col': None})

    if not raw_dfs:
        return pd.DataFrame(), [], _warn

    # ── マスターファイル特定 ──
    def _score(fname: str, df: pd.DataFrame) -> int:
        cols = list(df.columns)
        s = len(cols)
        if any('性別' in c for c in cols): s += 50
        if any('年齢' in c for c in cols): s += 50
        return s

    master_fname = max(raw_dfs, key=lambda f: _score(f, raw_dfs[f]))
    merged = raw_dfs[master_fname].copy()
    used   = [master_fname]

    # ── LEFT JOIN ──
    for _idx, (fname, df) in enumerate(raw_dfs.items()):
        if fname == master_fname:
            continue
        # ファイルごとに一意なサフィックス（インデックス使用で衝突回避）
        dup = {c: f'{c}__f{_idx}' for c in df.columns
               if c != 'ID' and c in merged.columns}
        df = df.rename(columns=dup)
        merged = merged.merge(df, on='ID', how='left')
        used.append(fname)

    # 重複列を除去（マスターの列を優先して保持）
    merged = merged.loc[:, ~merged.columns.duplicated(keep='first')]

    # ── 型・派生列 ──
    for c in ['性別', '年齢']:
        if c in merged.columns:
            s = merged[c]
            # 万一 DataFrame が返る場合は最初の列を使う
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
                merged[c] = s
            merged[c] = pd.to_numeric(s, errors='coerce')

    if '年齢' in merged.columns:
        _age = merged['年齢']
        if isinstance(_age, pd.DataFrame):
            _age = _age.iloc[:, 0]
        merged['年齢階級'] = pd.cut(
            _age, bins=AGE_BINS, labels=AGE_LABELS, right=True
        )
    if '性別' in merged.columns:
        _sex = merged['性別']
        # 値形式を自動検出: 1/0, 1/2, 文字列('男性'/'女性'/'男'/'女') すべて対応
        _uniq = set(_sex.dropna().unique())
        if _uniq <= {1, 2, 1.0, 2.0}:            # 1=男性, 2=女性 形式
            merged['性別_ラベル'] = _sex.map({1: '男性', 2: '女性', 1.0: '男性', 2.0: '女性'})
        elif _uniq <= {0, 1, 0.0, 1.0}:           # 1=男性, 0=女性 形式
            merged['性別_ラベル'] = _sex.map({1: '男性', 0: '女性', 1.0: '男性', 0.0: '女性'})
        else:                                       # 文字列形式
            _str_map = {'男性': '男性', '女性': '女性', '男': '男性', '女': '女性',
                        'M': '男性', 'F': '女性', 'm': '男性', 'f': '女性'}
            merged['性別_ラベル'] = _sex.astype(str).map(_str_map)

    # ── リスクフラグ ──
    def _fl(col: str, op: str, val) -> 'pd.Series':
        if col not in merged.columns:
            return pd.Series(False, index=merged.index)
        s = merged[col]
        if isinstance(s, pd.DataFrame):   # 重複列が残った場合の保険
            s = s.iloc[:, 0]
        if op == '<':  return s < val
        if op == '<=': return s <= val
        if op == '>=': return s >= val
        if op == '>':  return s > val
        return pd.Series(False, index=merged.index)

    merged['flag_歩行速度低下']      = _fl('歩行速度_mps', '<', 1.0)
    merged['flag_下肢筋力低下']      = _fl('5回立ち上がり_秒', '>=', 12.0)
    merged['flag_骨密度低下']        = _fl('Tスコア_SD', '<=', -1.0)
    merged['flag_MCI疑い']           = _fl('MoCA総得点', '<=', 25)
    merged['flag_嚥下機能低下リスク'] = _fl('EAT10総得点', '>=', 3)

    if 'SMI' in merged.columns and '性別' in merged.columns:
        merged['flag_サルコペニア疑い'] = (
            ((merged['性別'] == 1) & (merged['SMI'] < 7.0)) |
            ((merged['性別'] == 0) & (merged['SMI'] < 5.7))
        )
    else:
        merged['flag_サルコペニア疑い'] = False

    # 仮のAWGS2019（歩行速度 or 椅子立ち上がりのみ）→ 握力が揃ったら後で上書き
    merged['flag_AWGS2019サルコペニア'] = (
        merged['flag_サルコペニア疑い'] &
        (merged['flag_歩行速度低下'] | merged['flag_下肢筋力低下'])
    )

    if 'J_CHS' in merged.columns:
        j = pd.to_numeric(merged['J_CHS'], errors='coerce')
        merged['flag_プレフレイル'] = j.isin([1, 2])
        merged['flag_フレイル']    = j >= 3

    # ── 簡易フレイルインデックス（J-CHS準拠4項目）──
    # 実データ列名・値の仕様（分析用＿2025フレイル判定用.csv 確認済み）:
    #   6ヵ月体重減少_0_1 : '-'/0-4 のLikert → ≥1 を体重減少あり(1)に変換
    #   訳もなく疲れたように感じる_0_1 : 0-3 のLikert → ≥1 を疲れあり(1)に変換
    #   軽い運動plus定期的運動_0_1 : '#VALUE!'(→NaN)/1 → 1=活動あり(0リスク), NaN=不明
    #   4m歩行_1_0_値 : 0/1 バイナリ → 0=歩行低下(1リスク)
    # ※ 握力は #REF! のため除外。4項目合計、≥3 でフレイル。
    _frail_series: Dict[str, 'pd.Series'] = {}
    # 1. 体重減少（Likert → ≥1=リスク=1, 0=正常=0）
    for _fc in ['6ヵ月体重減少_0_1', '6ヶ月体重減少_0_1', '6ヶ月の体重減少_0_1', '体重低下_0_1']:
        if _fc in merged.columns:
            _v = pd.to_numeric(merged[_fc], errors='coerce')
            _frail_series['体重減少'] = (_v >= 1).where(_v.notna()).astype(float)
            break
    # 2. 疲れ（Likert 0-3 → ≥1=リスク=1, 0=正常=0）
    for _fc in ['訳もなく疲れたように感じる_0_1', '疲れ_0_1_値', '疲れ_0_1']:
        if _fc in merged.columns:
            _v = pd.to_numeric(merged[_fc], errors='coerce')
            _frail_series['疲れ'] = (_v >= 1).where(_v.notna()).astype(float)
            break
    # 3. 運動不足（活動あり=1=安全 → invert; #VALUE!→NaN → 不明=fillna(0)で安全扱い）
    for _fc in ['軽い運動plus定期的運動_0_1', '規則的な運動_0_1']:
        if _fc in merged.columns:
            _v = pd.to_numeric(merged[_fc], errors='coerce')
            # 1=活動あり→0(リスクなし), NaN→不明(fillna時に0=安全扱い)
            _frail_series['活動不足'] = (1 - _v).clip(0, 1)
            break
    # 4. 歩行速度低下（0=不通過=リスク=1, 1=通過=安全=0）
    if '4m歩行_1_0_値' in merged.columns:
        _v = pd.to_numeric(merged['4m歩行_1_0_値'], errors='coerce')
        _frail_series['歩行低下'] = (1 - _v).clip(0, 1)
    if _frail_series:
        _item_df = pd.DataFrame(_frail_series, index=merged.index)
        _has_any = _item_df.notna().any(axis=1)          # 少なくとも1項目回答あり
        _score   = _item_df.fillna(0).sum(axis=1)
        _score[~_has_any] = np.nan                        # 未回答者はNaN
        merged['簡易フレイルスコア'] = _score
        merged['flag_フレイル判定']     = np.where(_has_any, _score >= 3,           np.nan)
        merged['flag_プレフレイル判定'] = np.where(_has_any, (_score >= 1) & (_score < 3), np.nan)

    # 握力低下（参考指標として保持、AWGS2019には使用しない）
    _grip_col = next(
        (c for c in merged.columns
         if '握力' in str(c) and any(k in str(c) for k in ['最大値', '最大', 'max', 'Max'])),
        None
    )
    if _grip_col is None:
        for gc in ['左右握力最大値', '握力_最大値', '握力最大値', '握力']:
            if gc in merged.columns:
                _grip_col = gc
                break
    if _grip_col:
        _sex = merged.get('性別', pd.Series(np.nan, index=merged.index))
        merged['flag_握力低下'] = (
            ((_sex == 1) & (pd.to_numeric(merged[_grip_col], errors='coerce') < 28)) |
            ((_sex == 0) & (pd.to_numeric(merged[_grip_col], errors='coerce') < 18))
        )
    # AWGS2019確定サルコペニア: 低SMI + (歩行速度低下 OR 椅子立ち上がり低下)
    # ※ 握力は参考情報として別途 flag_握力低下 を保持
    merged['flag_サルコペニア確定'] = merged['flag_AWGS2019サルコペニア'].copy()

    # オーラルフレイル判定（列名を柔軟に検索：実ファイルは「オーラルフレイル_判定_」）
    oral_col = next(
        (c for c in merged.columns
         if 'オーラルフレイル' in str(c) and
         any(k in str(c) for k in ['判定', '総合', '得点'])),
        None
    )
    if oral_col:
        ov = pd.to_numeric(merged[oral_col], errors='coerce')
        merged['flag_オーラルフレイル'] = ov >= 1

    # バランス能力低下（列名を柔軟に検索：_read_csv_safeで\n→_に正規化後「バランス_得点」）
    bal_col = next(
        (c for c in merged.columns if 'バランス' in str(c) and '得点' in str(c)),
        None
    )
    if bal_col is None:
        for _bc in ['バランス 得点', 'バランス得点', 'SPPB_バランス']:
            if _bc in merged.columns:
                bal_col = _bc
                break
    if bal_col:
        merged['flag_バランス能力低下'] = pd.to_numeric(merged[bal_col], errors='coerce') < 4

    base_flags = [f'flag_{k}' for k in CUTOFFS if f'flag_{k}' in merged.columns]
    if base_flags:
        merged['リスク重複数'] = merged[base_flags].astype(float).sum(axis=1)

    return merged, used, _warn


def safe_pct(n: int, d: int) -> float:
    return round(n / d * 100, 1) if d > 0 else 0.0


def risk_stats(df: pd.DataFrame, flag_col: str, base_col: str) -> dict:
    if base_col not in df.columns or flag_col not in df.columns:
        return {'n_valid': 0, 'n_risk': 0, 'n_safe': 0, 'pct': 0.0}
    valid = df[base_col].notna()
    n_v = int(valid.sum())
    n_r = int(df.loc[valid, flag_col].sum()) if n_v > 0 else 0
    return {'n_valid': n_v, 'n_risk': n_r, 'n_safe': n_v - n_r,
            'pct': safe_pct(n_r, n_v)}


# ─── 3b. 統計エクスポート / ロード ──────────────────────────────────────────
def build_stats(df: pd.DataFrame) -> dict:
    """個人データを含まない集計統計を生成する（公開共有用）。"""
    import json as _json
    from datetime import date as _date
    N = len(df)

    def _flag_sum(col):
        if col not in df.columns:
            return 0
        return int(df[col].fillna(False).astype(bool).sum())

    # ── KPI 統計 ──
    kpi_out = {}
    for name, cfg in {**CUTOFFS, **FUTURE_INDICATORS}.items():
        fc = f'flag_{name}'
        if fc not in df.columns:
            continue
        bc = cfg.get('col')
        if bc and bc in df.columns:
            rs = risk_stats(df, fc, bc)
        else:
            n_v = int(df[fc].notna().sum())
            n_r = _flag_sum(fc)
            rs = {'n_valid': n_v, 'n_risk': n_r, 'n_safe': n_v - n_r,
                  'pct': safe_pct(n_r, n_v)}
        kpi_out[name] = {'n_valid': rs['n_valid'], 'n_risk': rs['n_risk'],
                         'pct': rs['pct'],
                         'icon': cfg['icon'], 'color': cfg['color']}

    # ── フレイル判定ヒーロー ──
    hero_valid = int(df['簡易フレイルスコア'].notna().sum()) if '簡易フレイルスコア' in df.columns else N
    hero_frail = _flag_sum('flag_フレイル判定')
    hero_pre   = _flag_sum('flag_プレフレイル判定')
    hero_normal = max(hero_valid - hero_frail - hero_pre, 0)

    # ── リスク重複数 ──
    risk_ov = {}
    if 'リスク重複数' in df.columns:
        for k, v in df['リスク重複数'].value_counts().sort_index().items():
            risk_ov[str(int(k))] = int(v)

    # ── バタフライ（年代×性別×指標） ──
    butterfly = {}
    if '年齢階級' in df.columns and '性別_ラベル' in df.columns:
        for name in {**CUTOFFS, **FUTURE_INDICATORS}:
            fc = f'flag_{name}'
            if fc not in df.columns:
                continue
            ages, m_p, f_p, t_p, m_n, f_n = [], [], [], [], [], []
            for ag in AGE_LABELS:
                if ag not in df['年齢階級'].values:
                    continue
                ms = df[(df['年齢階級'] == ag) & (df['性別_ラベル'] == '男性')]
                fs = df[(df['年齢階級'] == ag) & (df['性別_ラベル'] == '女性')]
                ts = df[df['年齢階級'] == ag]
                mr = int(ms[fc].fillna(False).astype(bool).sum())
                fr = int(fs[fc].fillna(False).astype(bool).sum())
                tr = int(ts[fc].fillna(False).astype(bool).sum())
                ages.append(ag)
                m_p.append(safe_pct(mr, len(ms))); m_n.append(len(ms))
                f_p.append(safe_pct(fr, len(fs))); f_n.append(len(fs))
                t_p.append(safe_pct(tr, len(ts)))
            if ages:
                butterfly[name] = {'age_labels': ages,
                                   'm_pcts': m_p, 'f_pcts': f_p, 't_pcts': t_p,
                                   'm_ns': m_n, 'f_ns': f_n}

    # ── 性別比較 ──
    sex_cmp = {'labels': [], 'icons': [], 'm_vals': [], 'f_vals': []}
    if '性別_ラベル' in df.columns:
        m_df = df[df['性別_ラベル'] == '男性']
        f_df = df[df['性別_ラベル'] == '女性']
        for name, cfg in {**CUTOFFS, **FUTURE_INDICATORS}.items():
            fc = f'flag_{name}'
            if fc not in df.columns:
                continue
            mr = int(m_df[fc].fillna(False).astype(bool).sum())
            fr = int(f_df[fc].fillna(False).astype(bool).sum())
            sex_cmp['labels'].append(f'{cfg["icon"]} {name}')
            sex_cmp['icons'].append(cfg['icon'])
            sex_cmp['m_vals'].append(safe_pct(mr, len(m_df)))
            sex_cmp['f_vals'].append(safe_pct(fr, len(f_df)))

    return {
        'meta': {
            'title': '村上市 総合フレイル分析ダッシュボード 2025',
            'generated_at': str(_date.today()),
            'N': N,
            'n_m': int((df['性別'] == 1).sum()) if '性別' in df.columns else 0,
            'n_f': int((df['性別'] == 0).sum()) if '性別' in df.columns else 0,
        },
        'kpi': kpi_out,
        'frail': {
            'hero_valid': hero_valid, 'hero_frail': hero_frail,
            'hero_pre': hero_pre, 'hero_normal': hero_normal,
            'pct_frail': safe_pct(hero_frail, hero_valid),
            'pct_pre':   safe_pct(hero_pre,   hero_valid),
            'pct_normal': safe_pct(hero_normal, hero_valid),
        },
        'risk_overlap': risk_ov,
        'butterfly': butterfly,
        'sex_compare': sex_cmp,
    }


def load_stats_json() -> Optional[dict]:
    """stats.json から集計統計を読み込む。"""
    import json as _json
    _sp = os.path.join(_HERE, 'stats.json')
    try:
        with open(_sp, 'r', encoding='utf-8') as _sf:
            return _json.load(_sf)
    except Exception:
        return None


# ─── 4. ページ設定 & CSS ─────────────────────────────────────────────────────
st.set_page_config(
    page_title='村上市 総合フレイル分析ダッシュボード 2025',
    page_icon='🏥', layout='wide',
    initial_sidebar_state='expanded',
)

st.markdown(f"""
<style>
/* ══ ページ背景 ═════════════════════════════════════════════════════════════ */
[data-testid="stAppViewContainer"] {{
    background:linear-gradient(160deg,#E4EBF6 0%,#EDF2FA 40%,#E8EFF7 100%);
    min-height:100vh;
}}
[data-testid="stHeader"]  {{ background:transparent; box-shadow:none; }}
[data-testid="stToolbar"] {{ display:none; }}
.block-container {{
    padding-top:1rem !important;
    padding-bottom:2.5rem !important;
    max-width:1280px;
}}

/* ══ サイドバー ══════════════════════════════════════════════════════════════ */
[data-testid="stSidebar"] {{
    background:rgba(255,255,255,0.82) !important;
    backdrop-filter:blur(18px);
    -webkit-backdrop-filter:blur(18px);
    border-right:1px solid rgba(180,200,220,0.45) !important;
    box-shadow:3px 0 24px rgba(15,32,68,0.07);
}}

/* ══ KPIカード（グラスモーフィズム） ═══════════════════════════════════════ */
.kpi {{
    background:rgba(255,255,255,0.86);
    backdrop-filter:blur(14px);
    -webkit-backdrop-filter:blur(14px);
    border-radius:16px;
    padding:18px 16px 14px;
    box-shadow:0 2px 6px rgba(15,32,68,0.06),0 8px 24px rgba(15,32,68,0.05);
    border:1px solid rgba(200,214,229,0.5);
    border-top:4px solid var(--c);
    height:100%;
    transition:transform .18s ease,box-shadow .18s ease;
}}
.kpi:hover {{
    transform:translateY(-2px);
    box-shadow:0 4px 12px rgba(15,32,68,0.09),0 14px 32px rgba(15,32,68,0.08);
}}
.kpi-icon {{ font-size:22px; margin-bottom:4px; }}
.kpi-name {{
    font-size:11px; font-weight:700; color:{P['muted']};
    letter-spacing:.07em; text-transform:uppercase; margin-bottom:6px;
}}
.kpi-pct  {{ font-size:34px; font-weight:800; line-height:1; color:var(--c); }}
.kpi-unit {{ font-size:14px; font-weight:500; color:{P['muted']}; }}
.kpi-det  {{ font-size:11.5px; color:{P['muted']}; margin-top:5px; font-weight:600; }}
.kpi-bar-bg   {{ background:rgba(200,214,229,0.45); border-radius:4px; height:5px; margin-top:10px; overflow:hidden; }}
.kpi-bar-fill {{ height:5px; border-radius:4px; background:var(--c); }}
.kpi-basis {{
    font-size:10px; color:{P['muted']}; margin-top:6px; line-height:1.45;
    background:rgba(235,241,248,0.7); border-radius:6px; padding:4px 6px;
}}

/* ══ セクション見出し ════════════════════════════════════════════════════════ */
.sec {{
    font-size:14px; font-weight:800; color:{P['navy']};
    border-left:4px solid {P['accent']};
    padding:2px 0 2px 12px; margin:24px 0 14px;
}}
.sec.red {{ border-color:{P['red']}; color:#8B1220; }}

/* ══ アラートカード ══════════════════════════════════════════════════════════ */
.alert {{
    background:rgba(254,242,242,0.9);
    backdrop-filter:blur(8px);
    border:1px solid rgba(252,200,200,0.8);
    border-left:4px solid {P['red']};
    border-radius:12px; padding:14px 18px; margin-bottom:14px;
    box-shadow:0 2px 8px rgba(197,41,59,0.08);
}}
.alert-n   {{ font-size:26px; font-weight:800; color:#991B1B; }}
.alert-sub {{ font-size:13px; color:#7F1D1D; font-weight:500; margin-left:8px; }}
.alert-tip {{ font-size:11px; color:#B91C1C; margin-top:3px; }}

/* ══ テキスト・ラベル ════════════════════════════════════════════════════════ */
[data-testid="stWidgetLabel"] p,[data-testid="stWidgetLabel"],
.stSelectbox>label p,.stMultiSelect>label p,.stSlider>label p,
.stRadio>label p,.stCheckbox>label p,
[role="radiogroup"] p,[role="radiogroup"] label p,
[data-testid="stExpander"] summary p,[data-testid="stExpander"] summary span,
[data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] td,
[data-testid="stMarkdownContainer"] th,
[data-testid="stSidebar"] label,[data-testid="stSidebar"] p {{
    color:{P['text']} !important; font-weight:600 !important;
}}
[data-testid="stExpander"] summary p {{
    font-weight:700 !important; color:{P['navy']} !important;
}}
[data-testid="stCaptionContainer"] p {{
    color:{P['muted']} !important; font-weight:500 !important;
}}
[data-testid="stMarkdownContainer"] table th {{
    background:rgba(235,241,248,0.8) !important;
    color:{P['navy']} !important; font-weight:700 !important;
}}

/* ══ タブ ════════════════════════════════════════════════════════════════════ */
[data-testid="stTabs"] [role="tab"] {{
    font-weight:700; font-size:13px; color:{P['muted']};
    border-radius:8px 8px 0 0;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color:{P['navy']}; background:rgba(255,255,255,0.7);
}}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
    background:rgba(232,239,247,0.6);
    backdrop-filter:blur(8px);
    border-radius:10px 10px 0 0;
    padding:4px 4px 0;
}}

/* ══ ダウンロードボタン ══════════════════════════════════════════════════════ */
[data-testid="stDownloadButton"]>button {{
    background:linear-gradient(135deg,#1E6391,#2F8BBF) !important;
    color:#fff !important; border:none !important;
    border-radius:10px !important; font-weight:700 !important;
    padding:9px 24px !important; font-size:13px !important;
    width:100%; margin-top:8px;
    box-shadow:0 3px 10px rgba(30,99,145,0.20);
    transition:opacity .15s ease,transform .15s ease;
}}
[data-testid="stDownloadButton"]>button:hover {{
    opacity:0.88 !important;
    transform:translateY(-1px) !important;
}}

/* ══ エクスパンダー ══════════════════════════════════════════════════════════ */
[data-testid="stExpander"] {{
    background:rgba(255,255,255,0.72) !important;
    backdrop-filter:blur(10px);
    border:1px solid rgba(200,214,229,0.5) !important;
    border-radius:12px !important;
}}
</style>
""", unsafe_allow_html=True)


# ─── 5. データ読み込み ────────────────────────────────────────────────────────
_STATS = load_stats_json()          # 集計JSONが存在すれば統計モードで起動
df_all, _files, _load_warn = load_merged()

if df_all.empty and _STATS is None:
    st.markdown(f"""
<div style="max-width:560px;margin:60px auto 0;text-align:center;">
  <div style="font-size:52px;margin-bottom:16px;">📂</div>
  <div style="font-size:22px;font-weight:800;color:{P['navy']};margin-bottom:8px;">
    CSVファイルをアップロードしてください
  </div>
  <div style="font-size:13px;color:{P['muted']};margin-bottom:32px;line-height:1.7;">
    村上市フレイル検診データ（CSV形式）をアップロードすると<br>
    分析ダッシュボードが表示されます。<br>
    複数ファイルは自動でIDをキーに統合されます。
  </div>
</div>
""", unsafe_allow_html=True)
    ups = st.file_uploader(
        'CSVファイルをここにドラッグ＆ドロップ（複数ファイル同時選択可）',
        type=['csv'],
        accept_multiple_files=True,
    )
    if not ups:
        st.stop()
    _ubytes_list = tuple(f.read() for f in ups)
    df_all, _files, _load_warn = load_merged(uploaded_files=_ubytes_list)

    # ── 診断パネル ──
    if _load_warn:
        with st.expander('📋 ファイル読み込み診断', expanded=(df_all.empty)):
            for _w in _load_warn:
                _icon = {'ok': '✅', 'skip': '⚠️', 'no_id': '❌', 'error': '❌'}.get(_w['status'], '❓')
                st.markdown(f"**{_icon} {_w['file']}** — {_w['reason']}")
                if _w['rows']:
                    st.caption(f"　行数: {_w['rows']}行 ／ 列数: {len(_w['cols'])}列")
                if _w.get('id_col'):
                    st.caption(f"　ID列として使用: `{_w['id_col']}`")
                if _w['cols']:
                    st.caption(f"　検出列: {', '.join(_w['cols'][:30])}")
            if not df_all.empty:
                st.markdown('---')
                st.caption(f"統合後: {len(df_all)}名 ／ {len(df_all.columns)}列")
                _all_indicators = {**CUTOFFS, **FUTURE_INDICATORS}
                _missing = [n for n, cfg in _all_indicators.items()
                            if cfg.get('col') and cfg['col'] not in df_all.columns]
                _present = [n for n, cfg in _all_indicators.items()
                            if cfg.get('col') and cfg['col'] in df_all.columns]
                if _present:
                    st.caption(f"✅ 表示可能な指標: {', '.join(_present)}")
                if _missing:
                    st.caption(f"⚠️ データ不足の指標: {', '.join(_missing)}")

    if df_all.empty:
        st.error('ファイルの読み込みに失敗しました。診断パネルを確認してください。')
        st.stop()

# stats.json がある場合は CSV なしで統計モード起動
if df_all.empty and _STATS is not None:
    import json as _json
    _sm = _STATS['meta']
    _sk = _STATS['kpi']
    _sf = _STATS['frail']
    _sb = _STATS.get('butterfly', {})
    _sc = _STATS.get('sex_compare', {})
    _so = _STATS.get('risk_overlap', {})
    _sN = _sm['N']

    st.markdown(f"""
<div style="background:rgba(255,255,255,0.7);border-radius:12px;padding:10px 18px;
            margin-bottom:18px;border:1px solid rgba(180,200,220,.4);
            font-size:12px;color:{P['muted']};display:flex;gap:10px;align-items:center;">
  <span style="font-size:18px;">📊</span>
  <span>集計統計モード ─ 生成日: <b>{_sm.get('generated_at','')}</b>
  ／ 対象 <b>{_sN:,}名</b>（個人データは含まれません）</span>
</div>""", unsafe_allow_html=True)

    # ── Tab表示 ──
    _tab1s, _tab2s, _tab3s = st.tabs(['📋 サマリー', '🔬 詳細分析', '🚨 フォローアップ'])

    with _tab1s:
        # フレイルヒーロー
        _shf = _sf['hero_frail']; _shv = _sf['hero_valid']
        _shp = _sf['pct_pre'];    _shn = _sf['hero_normal']
        st.markdown(f"""
<div style="background:linear-gradient(135deg,#4A1428 0%,#7A2340 55%,#9B3054 100%);
            border-radius:14px;padding:16px 20px;color:#fff;margin-bottom:18px;
            display:flex;align-items:center;gap:16px;">
  <div style="flex:1;border-right:1px solid rgba(255,255,255,.2);padding-right:16px;">
    <div style="font-size:9px;font-weight:700;opacity:.75;letter-spacing:.08em;">フレイル該当率</div>
    <div style="font-size:40px;font-weight:800;line-height:1.1;">{_sf['pct_frail']:.1f}<span style="font-size:18px;">%</span></div>
    <div style="font-size:11px;opacity:.8;">{_shf:,}名 / {_shv:,}名</div>
  </div>
  <div style="display:flex;gap:10px;">
    <div style="background:rgba(255,255,255,.12);border-radius:8px;padding:10px 14px;text-align:center;">
      <div style="font-size:8px;opacity:.75;">プレフレイル</div>
      <div style="font-size:20px;font-weight:800;color:#FFD8E4;">{_shp:.1f}%</div>
      <div style="font-size:9px;opacity:.7;">{_sf['hero_pre']:,}名</div>
    </div>
    <div style="background:rgba(255,255,255,.12);border-radius:8px;padding:10px 14px;text-align:center;">
      <div style="font-size:8px;opacity:.75;">健常</div>
      <div style="font-size:20px;font-weight:800;color:#C8F5E0;">{_sf['pct_normal']:.1f}%</div>
      <div style="font-size:9px;opacity:.7;">{_shn:,}名</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

        # KPIカード
        _scols = st.columns(min(5, len(_sk)))
        for _si, (_sname, _skv) in enumerate(_sk.items()):
            with _scols[_si % len(_scols)]:
                st.markdown(f"""
<div class="kpi" style="--c:{_skv['color']}">
  <div class="kpi-icon">{_skv['icon']}</div>
  <div class="kpi-name">{_sname}</div>
  <div class="kpi-pct">{_skv['pct']:.1f}<span class="kpi-unit">%</span></div>
  <div class="kpi-det">{_skv['n_risk']:,} / {_skv['n_valid']:,}名</div>
</div>""", unsafe_allow_html=True)

        st.markdown('<br>', unsafe_allow_html=True)

        # レーダーチャート
        if _sk:
            _sr_names = [f'{v["icon"]} {k}' for k, v in _sk.items()]
            _sr_vals  = [v['pct'] for v in _sk.values()]
            _sr_clr   = list(_sk.values())[0]['color'] if _sk else '#9B3054'
            _sfig_r = go.Figure(go.Scatterpolar(
                r=_sr_vals + [_sr_vals[0]], theta=_sr_names + [_sr_names[0]],
                fill='toself',
                fillcolor=f'rgba(155,48,84,.10)',
                line=dict(color='#9B3054', width=2.5),
                mode='lines+markers+text',
                text=[f'{v:.0f}%' for v in _sr_vals] + [''],
                textposition='top center',
                textfont=dict(size=11, color=P['text']),
            ))
            _sfig_r.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, max(_sr_vals or [100]) * 1.25],
                                           tickfont=dict(size=11), gridcolor='rgba(180,200,220,.5)'),
                           angularaxis=dict(tickfont=dict(size=13, color=P['navy']))),
                showlegend=False, height=500,
                margin=dict(t=60, b=60, l=100, r=100),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            )
            st.plotly_chart(_sfig_r, use_container_width=True, config={'displayModeBar': False})

        # リスク重複バー
        if _so:
            _so_keys = [str(k) for k in sorted(int(k) for k in _so)]
            _so_vals = [_so[k] for k in _so_keys]
            _RISK_CLR = {0: '#52B788', 1: '#E9C46A', 2: '#E89060', 3: '#CF6080'}
            _so_clrs  = [_RISK_CLR.get(min(int(k), 3), '#CF6080') for k in _so_keys]
            _sfig_o = go.Figure(go.Bar(x=_so_keys, y=_so_vals, marker_color=_so_clrs,
                                       text=_so_vals, textposition='outside'))
            _sfig_o.update_layout(
                xaxis_title='リスク重複数（項目）', yaxis_title='人数',
                height=280, margin=dict(t=20, b=40, l=20, r=20),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            )
            st.markdown('<div class="sec">📊 リスク重複項目数の分布</div>', unsafe_allow_html=True)
            st.plotly_chart(_sfig_o, use_container_width=True, config={'displayModeBar': False})

    with _tab2s:
        if _sb:
            _sel = st.selectbox('指標を選択', list(_sb.keys()))
            _sbd = _sb[_sel]
            _scfg_sel = {**CUTOFFS, **FUTURE_INDICATORS}.get(_sel, {})
            _M_CLR = '#5B95C8'; _F_CLR = '#C97B9D'
            _sfig2 = go.Figure()
            _sfig2.add_trace(go.Bar(
                name='男性', y=_sbd['age_labels'], x=[-p for p in _sbd['m_pcts']],
                orientation='h', marker_color=_M_CLR,
                text=[f"{p:.1f}%" for p in _sbd['m_pcts']], textposition='inside',
                insidetextanchor='middle', textfont=dict(color='#fff', size=11),
            ))
            _sfig2.add_trace(go.Bar(
                name='女性', y=_sbd['age_labels'], x=_sbd['f_pcts'],
                orientation='h', marker_color=_F_CLR,
                text=[f"{p:.1f}%" for p in _sbd['f_pcts']], textposition='inside',
                insidetextanchor='middle', textfont=dict(color='#fff', size=11),
            ))
            _sfig2.update_layout(
                barmode='overlay',
                xaxis=dict(tickformat='.0f', ticksuffix='%',
                           tickvals=[-60,-40,-20,0,20,40,60],
                           ticktext=['60%','40%','20%','0%','20%','40%','60%']),
                height=max(320, len(_sbd['age_labels']) * 68 + 90),
                legend=dict(orientation='h', y=1.05, x=0.5, xanchor='center'),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(t=60, b=20, l=10, r=20),
                title=dict(text=f'{_scfg_sel.get("icon","📊")} {_sel} ─ 性別×年齢階級別',
                           font=dict(size=14, color=P['navy'])),
            )
            st.plotly_chart(_sfig2, use_container_width=True, config={'displayModeBar': False})

        if _sc.get('labels'):
            _sfig_c = go.Figure()
            _sfig_c.add_trace(go.Bar(name='男性', x=_sc['labels'], y=_sc['m_vals'],
                                     marker_color='#5B95C8', text=[f'{v:.1f}%' for v in _sc['m_vals']],
                                     textposition='outside'))
            _sfig_c.add_trace(go.Bar(name='女性', x=_sc['labels'], y=_sc['f_vals'],
                                     marker_color='#C97B9D', text=[f'{v:.1f}%' for v in _sc['f_vals']],
                                     textposition='outside'))
            _sfig_c.update_layout(
                barmode='group', yaxis=dict(range=[0, 130], ticksuffix='%'),
                height=340, margin=dict(t=30, b=20, l=0, r=0),
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            )
            st.markdown('<div class="sec">📊 全指標 男女別リスク率比較</div>', unsafe_allow_html=True)
            st.plotly_chart(_sfig_c, use_container_width=True, config={'displayModeBar': False})

    with _tab3s:
        st.info('🔒 フォローアップ対象者リストは個別データのため、この共有ビューでは非公開です。')

    st.stop()  # 統計モードのみで終了（CSV読み込み処理に進まない）


# ─── 6. サイドバー ────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f'<div style="font-size:13px;font-weight:800;color:{P["navy"]};'
        f'border-bottom:2px solid {P["blue"]};padding-bottom:5px;margin-bottom:12px;">'
        '🔍 データフィルター</div>', unsafe_allow_html=True
    )

    sex_opts = (sorted(df_all['性別_ラベル'].dropna().unique().tolist())
                if '性別_ラベル' in df_all.columns else [])
    sel_sex = st.multiselect('性別', sex_opts, default=sex_opts)

    age_present = ([l for l in AGE_LABELS
                    if l in df_all['年齢階級'].dropna().unique().tolist()]
                   if '年齢階級' in df_all.columns else [])
    sel_age = st.multiselect('年齢階級', age_present, default=age_present)

    st.divider()
    st.caption(f'📂 読込ファイル ({len(_files)}件)')
    for f in _files:
        st.caption(f'  • {f}')
    st.divider()
    st.caption('※ フィルターは全タブに即時反映')
    st.divider()
    st.markdown(f'<div style="font-size:11px;font-weight:800;color:{P["navy"]};margin-bottom:6px;">📤 外部共有用エクスポート</div>',
                unsafe_allow_html=True)
    st.caption('個人データを含まない集計統計を出力します。')
    if st.button('統計データを出力（stats.json）', use_container_width=True):
        import json as _ejson
        _estats = build_stats(df)
        _ejson_str = _ejson.dumps(_estats, ensure_ascii=False, indent=2)
        st.download_button(
            label='⬇️ stats.json をダウンロード',
            data=_ejson_str.encode('utf-8'),
            file_name='stats.json',
            mime='application/json',
            use_container_width=True,
        )
        st.success('ダウンロード後、stats.json をプロジェクトフォルダに置いてGitにプッシュしてください。')


# ── フィルター適用 ──
df = df_all.copy()
if sel_sex and '性別_ラベル' in df.columns:
    df = df[df['性別_ラベル'].isin(sel_sex)]
if sel_age and '年齢階級' in df.columns:
    df = df[df['年齢階級'].isin(sel_age)]

N = len(df)
if N == 0:
    st.warning('該当データがありません。フィルターを緩めてください。')
    st.stop()


# ─── 7. ヘッダーバナー ───────────────────────────────────────────────────────
n_m = int((df_all['性別'] == 1).sum()) if '性別' in df_all.columns else 0
n_f = int((df_all['性別'] == 0).sum()) if '性別' in df_all.columns else 0

_logo_html = (
    f'<img src="data:image/png;base64,{_HAL_LOGO_B64}" '
    'style="height:52px;width:auto;object-fit:contain;'
    'filter:drop-shadow(0 1px 4px rgba(0,0,0,.18));flex-shrink:0;">'
    if _HAL_LOGO_B64 else
    '<div style="background:rgba(255,255,255,.18);border-radius:10px;'
    'padding:8px 14px;text-align:center;flex-shrink:0;">'
    '<span style="font-size:16px;font-weight:900;color:#fff;letter-spacing:.05em;">HAL Lab.</span>'
    '<div style="font-size:9px;color:rgba(255,255,255,.75);margin-top:2px;">ヘルシーエイジング</div>'
    '</div>'
)

st.markdown(f"""
<div style="
    background:linear-gradient(135deg,{P['navy']} 0%,#1A4A8A 50%,{P['blue']} 100%);
    border-radius:18px;padding:20px 28px;margin-bottom:22px;
    display:flex;align-items:center;gap:20px;
    box-shadow:0 4px 20px rgba(15,32,68,0.20),0 1px 4px rgba(15,32,68,0.12);
    border:1px solid rgba(255,255,255,0.12);
    position:relative;overflow:hidden;">
  <!-- 背景装飾 -->
  <div style="position:absolute;right:-40px;top:-40px;width:200px;height:200px;
              border-radius:50%;background:rgba(255,255,255,0.04);pointer-events:none;"></div>
  <div style="position:absolute;right:60px;bottom:-60px;width:160px;height:160px;
              border-radius:50%;background:rgba(249,115,22,0.08);pointer-events:none;"></div>
  <!-- ロゴ -->
  <div style="flex-shrink:0;background:rgba(255,255,255,0.92);
              border-radius:12px;padding:8px 12px;
              box-shadow:0 2px 8px rgba(0,0,0,0.15);">
    {_logo_html}
  </div>
  <!-- タイトル -->
  <div style="flex:1;min-width:0;">
    <div style="font-size:8px;font-weight:700;color:{P['accent']};
                letter-spacing:.14em;text-transform:uppercase;margin-bottom:4px;
                text-shadow:0 1px 3px rgba(0,0,0,0.2);">
      HEALTHY AGING RESEARCH INSTITUTE
    </div>
    <div style="font-size:19px;font-weight:800;color:#fff;line-height:1.25;
                letter-spacing:.01em;text-shadow:0 1px 4px rgba(0,0,0,0.2);">
      村上市 高齢者総合検診 2025年度<br>
      <span style="font-size:15px;font-weight:700;opacity:0.9;">
        総合フレイル分析ダッシュボード
      </span>
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,.78);margin-top:6px;
                font-weight:500;letter-spacing:.03em;">
      AWGS2019・WHO基準準拠 ／ 高齢者支援課・保健師・行政幹部向け
    </div>
  </div>
  <!-- 統計バッジ -->
  <div style="flex-shrink:0;text-align:right;">
    <div style="background:rgba(249,115,22,0.18);border:1px solid rgba(249,115,22,0.4);
                border-radius:12px;padding:10px 16px;min-width:100px;">
      <div style="font-size:28px;font-weight:900;color:#fff;line-height:1;
                  text-shadow:0 1px 4px rgba(0,0,0,0.2);">{len(df_all):,}</div>
      <div style="font-size:10px;color:rgba(255,255,255,.75);margin-top:3px;font-weight:600;">
        対象者数（名）
      </div>
      <div style="font-size:10px;color:rgba(255,255,255,.65);margin-top:1px;">
        男性 {n_m} ／ 女性 {n_f}
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


# ─── 共通変数（タブ横断）────────────────────────────────────────────────────
active_flags: List[Tuple[str, dict]] = [
    (name, cfg) for name, cfg in CUTOFFS.items()
    if cfg['col'] in df.columns and f'flag_{name}' in df.columns
]
avail_names = [name for name, _ in active_flags]

kpi_data: Dict[str, dict] = {
    name: risk_stats(df, f'flag_{name}', cfg['col'])
    for name, cfg in active_flags
}

def _flag_stats(df: pd.DataFrame, flag_col: str) -> dict:
    """flag列のみからリスク統計を計算（base列不要）。"""
    if flag_col not in df.columns:
        return {'n_valid': 0, 'n_risk': 0, 'n_safe': 0, 'pct': 0.0}
    valid = df[flag_col].notna()
    n_v = int(valid.sum())
    n_r = int(df.loc[valid, flag_col].astype(bool).sum()) if n_v > 0 else 0
    return {'n_valid': n_v, 'n_risk': n_r, 'n_safe': n_v - n_r, 'pct': safe_pct(n_r, n_v)}

# ── 統合KPIリスト（DISPLAY_ORDER に従い CUTOFFS + FUTURE_INDICATORS を統合）──
ALL_INDICATORS: Dict = {**CUTOFFS, **FUTURE_INDICATORS}

unified_kpi: List[Tuple[str, dict, dict]] = []
for _uname in DISPLAY_ORDER:
    if _uname not in ALL_INDICATORS:
        continue
    _ucfg  = ALL_INDICATORS[_uname]
    _uflag = f'flag_{_uname}'
    if _uflag not in df.columns:
        continue
    if _uname in CUTOFFS and _ucfg.get('col') and _ucfg['col'] in df.columns:
        _ust = risk_stats(df, _uflag, _ucfg['col'])
    else:
        _ust = _flag_stats(df, _uflag)
    if _ust['n_valid'] > 0:
        unified_kpi.append((_uname, _ucfg, _ust))

# フレイル判定ヒーローカード統計
_hero_valid = int(df['簡易フレイルスコア'].notna().sum()) if '簡易フレイルスコア' in df.columns else 0
_hero_frail = int((df.get('flag_フレイル判定', pd.Series(0, index=df.index))
                   .fillna(0).astype(bool)).sum())
_hero_pre   = int((df.get('flag_プレフレイル判定', pd.Series(0, index=df.index))
                   .fillna(0).astype(bool)).sum())
_hero_pct_frail = safe_pct(_hero_frail, _hero_valid)
_hero_pct_pre   = safe_pct(_hero_pre,   _hero_valid)
_hero_pct_normal = safe_pct(max(_hero_valid - _hero_frail - _hero_pre, 0), _hero_valid)

# プレースホルダー：利用不可の指標
_avail_names_set = {n for n, _, _ in unified_kpi}
ph_list: List[Tuple[str, dict]] = [
    (name, cfg) for name, cfg in ALL_INDICATORS.items()
    if name in DISPLAY_ORDER and name not in _avail_names_set
]

# FUTURE_INDICATORS のうちフラグが計算済みのもの（旧 avail_future ─ 後方互換）
avail_future: List[Tuple[str, dict]] = [
    (n, c) for n, c, _ in unified_kpi if n in FUTURE_INDICATORS
]
future_kpi: Dict[str, dict] = {n: s for n, _, s in unified_kpi if n in FUTURE_INDICATORS}

# ── 散布図用指標セット（実測値がある指標のみ）──
SCATTER_OPTS: Dict[str, dict] = {}
for _sname, _scfg in ALL_INDICATORS.items():
    _scol  = _scfg.get('col')
    _sflag = f'flag_{_sname}'
    if _scol and _scol in df.columns and _sflag in df.columns:
        SCATTER_OPTS[_sname] = {
            'col': _scol, 'flag': _sflag,
            'val': _scfg.get('val'), 'op': _scfg.get('op'),
            'icon': _scfg['icon'], 'color': _scfg['color'],
        }

# ── Tab2/Tab3 で使う全指標リスト（CUTOFFS + FUTURE 統合）──
all_tab_indicators: List[Tuple[str, dict]] = [
    (name, {
        **cfg,
        'flag_col': f'flag_{name}',
        'base_col': (cfg.get('col') if cfg.get('col') and cfg['col'] in df.columns else None),
    })
    for name, cfg, _ in unified_kpi
]
all_tab_names = [n for n, _ in all_tab_indicators]
all_tab_cfg   = {n: c for n, c in all_tab_indicators}


# ─── 7b. 印刷用HTMLジェネレーター ───────────────────────────────────────────
def _make_report_html(title: str, subtitle: str, kpi_rows_html: str,
                      figs_html: str, logo_b64: str) -> str:
    """A4縦シンデレラフィット対応の自己完結型HTMLレポートを生成する。
    印刷時: @page A4 portrait, margin 10mm 12mm → 有効領域 186mm × 277mm ≈ 703px × 1047px
    """
    _logo_tag = (
        f'<img src="data:image/png;base64,{logo_b64}" '
        'style="height:40px;width:auto;vertical-align:middle;">'
        if logo_b64 else
        '<span style="font-size:16px;font-weight:900;color:#F97316;">HAL Lab.</span>'
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
/* ── 印刷基本設定 ────────────────────────────── */
@page {{
  size: A4 portrait;
  margin: 10mm 12mm;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{
  font-size: 10.5px;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}
body {{
  font-family: 'Hiragino Sans', 'Meiryo', 'Yu Gothic', sans-serif;
  color: #1E2D40;
  background: #fff;
  width: 186mm;
  max-width: 186mm;
  line-height: 1.45;
}}
/* ── ヘッダー ───────────────────────────────── */
.rpt-header {{
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 2.5px solid #F97316;
  padding-bottom: 8px;
  margin-bottom: 11px;
}}
.rpt-logo-box {{
  background: #F5F8FC;
  border-radius: 8px;
  padding: 5px 9px;
  flex-shrink: 0;
  border: 1px solid #E2E8F0;
}}
.rpt-header-text h1 {{
  font-size: 14px;
  font-weight: 800;
  color: #0F2044;
  line-height: 1.25;
}}
.rpt-header-text p {{
  font-size: 8.5px;
  color: #526070;
  margin-top: 2px;
  font-weight: 500;
}}
.rpt-badge {{
  margin-left: auto;
  flex-shrink: 0;
  background: #0F2044;
  color: #fff;
  font-size: 8px;
  font-weight: 700;
  padding: 4px 9px;
  border-radius: 5px;
  letter-spacing: .04em;
}}
/* ── セクション見出し ─────────────────────────── */
.sec-title {{
  font-size: 11px;
  font-weight: 800;
  color: #0F2044;
  border-left: 3.5px solid #F97316;
  padding-left: 7px;
  margin: 10px 0 6px;
  line-height: 1.3;
}}
/* ── フレイル判定バー ─────────────────────────── */
.hero-bar {{
  display: flex;
  align-items: stretch;
  gap: 0;
  background: linear-gradient(135deg, #4A1428 0%, #7A2340 55%, #9B3054 100%);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 9px;
  color: #fff;
}}
.hero-main {{
  flex: 1;
  padding-right: 14px;
  border-right: 1px solid rgba(255,255,255,.2);
  margin-right: 14px;
}}
.hero-main .label {{ font-size: 8px; font-weight: 700; opacity: .75; letter-spacing: .06em; }}
.hero-main .pct {{ font-size: 34px; font-weight: 800; line-height: 1; margin: 3px 0; }}
.hero-main .sub {{ font-size: 9px; opacity: .8; }}
.hero-sub {{ display: flex; gap: 10px; align-items: center; }}
.hero-sub-item {{
  background: rgba(255,255,255,.10);
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 6px;
  padding: 8px 10px;
  min-width: 80px;
  text-align: center;
}}
.hero-sub-item .label {{ font-size: 7.5px; font-weight: 700; opacity: .72; margin-bottom: 3px; }}
.hero-sub-item .pct {{ font-size: 18px; font-weight: 800; color: #FFD8E4; line-height: 1.1; }}
.hero-sub-item.green .pct {{ color: #C8F5E0; }}
.hero-sub-item .n {{ font-size: 8px; opacity: .70; margin-top: 2px; }}
/* ── KPIグリッド ─────────────────────────────── */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 5px;
  margin-bottom: 9px;
}}
.kpi-card {{
  background: #F5F8FC;
  border-radius: 7px;
  padding: 7px 6px;
  border-top: 2.5px solid var(--c);
  text-align: center;
}}
.kpi-card .icon {{ font-size: 13px; }}
.kpi-card .name {{
  font-size: 7.5px; font-weight: 700; color: #526070;
  letter-spacing: .04em; margin: 2px 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.kpi-card .pct {{ font-size: 18px; font-weight: 800; color: var(--c); line-height: 1.15; }}
.kpi-card .det {{ font-size: 7px; color: #526070; margin-top: 2px; }}
/* ── チャートコンテナ ─────────────────────────── */
.chart-wrap {{
  margin: 4px 0;
  page-break-inside: avoid;
  width: 100%;
  overflow: hidden;
}}
/* Plotlyチャートを幅に収める */
.js-plotly-plot, .plotly {{
  max-width: 186mm !important;
  overflow: hidden !important;
}}
.modebar {{ display: none !important; }}
/* ── フッター ────────────────────────────────── */
.rpt-footer {{
  margin-top: 10px;
  padding-top: 7px;
  border-top: 1px solid #E2E8F0;
  font-size: 7.5px;
  color: #8A9BB0;
  text-align: center;
  line-height: 1.5;
}}
/* ── 印刷用メディアクエリ ──────────────────────── */
@media print {{
  body {{ width: 186mm; }}
  .chart-wrap {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
<!-- ヘッダー -->
<div class="rpt-header">
  <div class="rpt-logo-box">{_logo_tag}</div>
  <div class="rpt-header-text">
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </div>
  <div class="rpt-badge">村上市 高齢者支援課</div>
</div>
<!-- コンテンツ -->
{kpi_rows_html}
<!-- チャート -->
{figs_html}
<!-- フッター -->
<div class="rpt-footer">
  AWGS2019 / WHO 1994 / Nasreddine 2005 / Belafsky 2008 / J-CHS 2020 準拠 ｜
  村上市高齢者総合検診フレイル分析ダッシュボード ｜ HAL Lab. ヘルシーエイジング・長寿研究所
</div>
</body>
</html>"""


# ─── 8. タブ ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    '📊  サマリー（全体リスク可視化）',
    '📈  詳細分析（性別・年代別クロス集計）',
    '🚨  フォローアップ対象者抽出',
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 ─ SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown(
        f'<div class="sec">📊 各指標リスク群サマリー（欠損値除外 N={N:,}名）</div>',
        unsafe_allow_html=True
    )

    # ── フレイル判定 ヒーローカード ──────────────────────────────────────────
    if _hero_valid > 0:
        st.markdown(f"""
<div style="background:linear-gradient(135deg,#4A1428 0%,#7A2340 55%,#9B3054 100%);
            border-radius:18px;padding:20px 26px;margin-bottom:18px;
            display:flex;align-items:center;gap:24px;flex-wrap:wrap;
            box-shadow:0 4px 20px rgba(74,20,40,0.18),0 1px 5px rgba(74,20,40,0.12);
            border:1px solid rgba(255,255,255,0.10);position:relative;overflow:hidden;">
  <div style="position:absolute;right:-30px;top:-30px;width:160px;height:160px;
              border-radius:50%;background:rgba(255,255,255,0.04);pointer-events:none;"></div>
  <div style="flex:0 0 auto;text-align:center;">
    <div style="font-size:40px;line-height:1;filter:drop-shadow(0 2px 5px rgba(0,0,0,.3));">🩺</div>
    <div style="font-size:10px;font-weight:800;color:rgba(255,255,255,.80);
                text-transform:uppercase;letter-spacing:.08em;margin-top:5px;">フレイル判定</div>
  </div>
  <div style="flex:1;min-width:140px;border-right:1px solid rgba(255,255,255,.22);
              padding-right:24px;margin-right:4px;">
    <div style="font-size:11px;color:rgba(255,255,255,.72);font-weight:600;margin-bottom:4px;">
      フレイル該当率（3点以上）</div>
    <div style="font-size:50px;font-weight:800;color:#fff;line-height:1;
                text-shadow:0 1px 6px rgba(0,0,0,0.2);">{_hero_pct_frail:.1f}<span style="font-size:20px;">%</span></div>
    <div style="font-size:12px;color:rgba(255,255,255,.78);margin-top:5px;font-weight:500;">
      {_hero_frail}名 フレイル ／ 判定N={_hero_valid}名
    </div>
    <div style="background:rgba(255,255,255,.15);border-radius:4px;height:5px;margin-top:10px;">
      <div style="height:5px;border-radius:4px;background:rgba(255,255,255,0.85);
                  width:{min(_hero_pct_frail,100):.1f}%;"></div>
    </div>
  </div>
  <div style="flex:1;min-width:180px;display:flex;gap:14px;align-items:center;">
    <div style="flex:1;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);
                border-radius:10px;padding:12px 14px;">
      <div style="font-size:10px;font-weight:700;color:rgba(255,255,255,.72);margin-bottom:4px;">
        🟡 プレフレイル（1-2点）</div>
      <div style="font-size:26px;font-weight:800;color:#FFD8E4;line-height:1.15;">{_hero_pct_pre:.1f}%</div>
      <div style="font-size:11px;color:rgba(255,255,255,.68);margin-top:3px;">{_hero_pre}名</div>
    </div>
    <div style="flex:1;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);
                border-radius:10px;padding:12px 14px;">
      <div style="font-size:10px;font-weight:700;color:rgba(255,255,255,.72);margin-bottom:4px;">
        🟢 健常（0点）</div>
      <div style="font-size:26px;font-weight:800;color:#C8F5E0;line-height:1.15;">{_hero_pct_normal:.1f}%</div>
      <div style="font-size:11px;color:rgba(255,255,255,.68);margin-top:3px;">
        {max(_hero_valid-_hero_frail-_hero_pre,0)}名</div>
    </div>
  </div>
  <div style="width:100%;padding-top:8px;margin-top:0;border-top:1px solid rgba(255,255,255,.14);
              font-size:10px;color:rgba(255,255,255,.60);">
    📐 簡易フレイルインデックス（体重減少・疲れ・活動不足・歩行低下・物忘れ）
    5項目合計スコア ≥3 でフレイル、1-2 でプレフレイル
  </div>
</div>""", unsafe_allow_html=True)

    # ── その他指標 KPI カード（DISPLAY_ORDER順、4列グリッド）──
    remaining_kpi = [(n, c, s) for n, c, s in unified_kpi if n != 'フレイル判定']

    if remaining_kpi:
        # 4列ずつ行を組む
        for _row_s in range(0, len(remaining_kpi), 4):
            _row = remaining_kpi[_row_s:_row_s + 4]
            _row_cols = st.columns(len(_row))
            for _ci, (_n, _c, _s) in enumerate(_row):
                _pct = _s['pct']
                with _row_cols[_ci]:
                    st.markdown(f"""
                    <div class="kpi" style="--c:{_c['color']};" title="📐 {_c['basis']}">
                      <div class="kpi-icon">{_c['icon']}</div>
                      <div class="kpi-name">{_n}</div>
                      <div><span class="kpi-pct">{_pct:.1f}</span>
                           <span class="kpi-unit">%</span></div>
                      <div class="kpi-det">リスク <b>{_s['n_risk']:,}名</b>
                           ／ 正常 {_s['n_safe']:,}名</div>
                      <div class="kpi-det">N = {_s['n_valid']:,}名</div>
                      <div class="kpi-bar-bg">
                        <div class="kpi-bar-fill" style="width:{min(_pct,100):.1f}%;"></div>
                      </div>
                      <div class="kpi-basis">📐 {_c['basis']}</div>
                    </div>""", unsafe_allow_html=True)
            st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

    # プレースホルダーカード（データ連携待ち）
    _ph_show = [(n, c) for n, c in ph_list if n != 'フレイル判定']
    if _ph_show:
        st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:11px;font-weight:700;color:{P["muted"]};'
            'text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">'
            '🔗 データ連携後に自動表示される指標</div>',
            unsafe_allow_html=True
        )
        _ph_row = [_ph_show[i:i+4] for i in range(0, len(_ph_show), 4)]
        for _phr in _ph_row:
            _ph_cols = st.columns(len(_phr))
            for _pi, (_pn, _pc) in enumerate(_phr):
                with _ph_cols[_pi]:
                    st.markdown(f"""
                    <div style="background:rgba(255,255,255,0.7);border:2px dashed rgba(148,163,184,0.6);
                                border-radius:14px;padding:14px 12px;">
                      <div style="font-size:11px;font-weight:700;color:{P['muted']};
                                  margin-bottom:4px;">{_pc['icon']} {_pn}</div>
                      <div style="font-size:26px;font-weight:800;color:#CBD5E1;
                                  letter-spacing:.1em;margin:4px 0;">— —</div>
                      <div style="font-size:10px;color:{P['muted']};background:#F8FAFC;
                                  border-left:3px solid #94A3B8;border-radius:0 5px 5px 0;
                                  padding:5px 8px;line-height:1.5;">
                        ⚠️ 評価用紙・測定データ連携待ち</div>
                    </div>""", unsafe_allow_html=True)

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # ── レーダーチャート（全幅）──────────────────────────────────────────────
    rl = [f'{CUTOFFS[n]["icon"]} {n}' for n in avail_names]
    rv = [kpi_data[n]['pct'] for n in avail_names]

    fig_r = go.Figure()
    fig_r.add_trace(go.Scatterpolar(
        r=[100]*len(avail_names) + [100], theta=rl + [rl[0]],
        fill='toself', fillcolor='rgba(210,225,245,.35)',
        line=dict(color='rgba(180,200,220,0.7)', width=1),
        showlegend=False, hoverinfo='skip',
    ))
    fig_r.add_trace(go.Scatterpolar(
        r=rv + [rv[0]], theta=rl + [rl[0]],
        fill='toself', fillcolor='rgba(155,48,84,.10)',
        line=dict(color='#9B3054', width=2.8),
        marker=dict(size=8, color='#9B3054',
                    line=dict(color='#fff', width=2)),
        hovertemplate='<b>%{theta}</b><br>%{r:.1f}%<extra></extra>',
    ))
    fig_r.update_layout(
        polar=dict(
            bgcolor='rgba(255,255,255,0.65)',
            radialaxis=dict(
                visible=True, range=[0, 100], ticksuffix='%',
                tickfont=dict(size=11, color=P['muted']),
                gridcolor='rgba(200,214,229,0.6)',
                linecolor='rgba(200,214,229,0.5)',
                tickvals=[25, 50, 75, 100],
            ),
            angularaxis=dict(
                tickfont=dict(size=13, color=P['navy']),
                gridcolor='rgba(200,214,229,0.5)',
                linecolor='rgba(200,214,229,0.4)',
            ),
        ),
        paper_bgcolor='rgba(255,255,255,0.88)', font=dict(color=P['text']),
        showlegend=False,
        margin=dict(t=80, b=80, l=110, r=110), height=540,
        title=dict(text=f'フレイル関連指標 リスク該当率マップ（フィルター適用後 N={N:,}名）',
                   font=dict(size=13, color=P['navy']), x=0.5),
    )
    st.plotly_chart(fig_r, use_container_width=True, config={'displayModeBar': False})

    # ── 指標別リスク該当率（横棒、全幅、レーダーの下）──────────────────────
    st.markdown(
        '<div class="sec" style="margin-top:8px;">📊 指標別リスク該当率（昇順）</div>',
        unsafe_allow_html=True
    )
    s_order = sorted(avail_names, key=lambda n: kpi_data[n]['pct'])
    yl  = [f'{CUTOFFS[n]["icon"]} {n}' for n in s_order]
    xv  = [kpi_data[n]['pct']    for n in s_order]
    nr  = [kpi_data[n]['n_risk']  for n in s_order]
    nt  = [kpi_data[n]['n_valid'] for n in s_order]
    bc  = [CUTOFFS[n]['color']   for n in s_order]

    fig_hb = go.Figure()
    fig_hb.add_trace(go.Bar(
        y=yl, x=[100]*len(s_order), orientation='h',
        marker_color='rgba(226,232,240,0.55)', marker_line_width=0,
        showlegend=False, hoverinfo='skip',
    ))
    fig_hb.add_trace(go.Bar(
        y=yl, x=xv, orientation='h',
        marker_color=bc, marker_line_width=0,
        text=[f'<b>{v:.1f}%</b>  {n}/{t}名'
              for v, n, t in zip(xv, nr, nt)],
        textposition='outside',
        textfont=dict(size=12, color=P['navy']),
        hovertemplate='%{y}: %{x:.1f}%<extra></extra>',
    ))
    fig_hb.update_layout(
        barmode='overlay',
        xaxis=dict(range=[0, 155], ticksuffix='%',
                   gridcolor='rgba(226,232,240,0.6)',
                   tickfont=dict(size=11, color=P['text'])),
        yaxis=dict(tickfont=dict(size=13, color=P['text']), title=None),
        paper_bgcolor='rgba(255,255,255,0.88)',
        plot_bgcolor='rgba(248,250,252,0.6)',
        font=dict(color=P['text']),
        showlegend=False,
        margin=dict(t=20, b=10, l=0, r=120),
        height=max(260, len(s_order) * 38 + 50),
    )
    st.plotly_chart(fig_hb, use_container_width=True, config={'displayModeBar': False})

    # リスク重複数分布
    if 'リスク重複数' in df.columns:
        st.markdown('<div class="sec">🔢 フレイルリスク重複数の分布</div>', unsafe_allow_html=True)
        col_dist, col_leg = st.columns([2.2, 1])

        with col_dist:
            rc    = df['リスク重複数'].value_counts().sort_index()
            xr    = [f'{int(k)} 項目' for k in rc.index]
            yr    = rc.values.astype(float)
            total = yr.sum()
            pr    = yr / total * 100 if total > 0 else yr * 0
            # 清潔感のある淡いパステル調パレット
            _RISK_CLR = {0: '#52B788', 1: '#E9C46A', 2: '#E89060', 3: '#CF6080'}
            bc2 = [_RISK_CLR.get(min(int(k), 3), '#CF6080') for k in rc.index]

            fig_rd = go.Figure(go.Bar(
                x=xr, y=yr, marker_color=bc2, marker_line_width=0,
                text=[f'<b>{p:.1f}%</b><br>{int(n)}名' for p, n in zip(pr, yr)],
                textposition='outside',
                textfont=dict(size=11, color=P['text']),
                hovertemplate='%{x}: %{y:.0f}名<extra></extra>',
            ))
            fig_rd.update_layout(
                xaxis=dict(title='リスク重複項目数',
                           tickfont=dict(size=12, color=P['text']),
                           title_font=dict(color=P['text'])),
                yaxis=dict(title='人数（名）', gridcolor='#E2E8F0',
                           tickfont=dict(size=10, color=P['text']),
                           title_font=dict(color=P['text'])),
                paper_bgcolor='rgba(255,255,255,0.88)', plot_bgcolor='rgba(255,255,255,0.7)',
                font=dict(color=P['text']),
                showlegend=False, margin=dict(t=40, b=10, l=0, r=0), height=280,
            )
            st.plotly_chart(fig_rd, use_container_width=True, config={'displayModeBar': False})

        with col_leg:
            n0  = int((df['リスク重複数'] == 0).sum())
            n1  = int((df['リスク重複数'] == 1).sum())
            n2  = int((df['リスク重複数'] == 2).sum())
            n3p = int((df['リスク重複数'] >= 3).sum())
            items = [
                ('#52B788', n0,  '名 — 全項目正常'),
                ('#E9C46A', n1,  '名 — 1項目リスク ⚠️'),
                ('#E89060', n2,  '名 — 2項目リスク 🔶'),
                ('#CF6080', n3p, '名 — 3項目以上 🚨'),
            ]
            rows_html = ''.join([
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
                f'<div style="width:10px;height:10px;border-radius:50%;background:{c};flex-shrink:0;"></div>'
                f'<span style="font-size:22px;font-weight:800;color:{c};">{n}</span>'
                f'<span style="font-size:12px;color:{P["muted"]};font-weight:600;">{l}</span>'
                f'</div>'
                for c, n, l in items
            ])
            st.markdown(
                f'<div style="background:rgba(255,255,255,0.86);backdrop-filter:blur(10px);border-radius:12px;padding:18px 16px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,.07);">'
                f'{rows_html}'
                f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid #F1F5F9;'
                f'font-size:11px;color:{P["muted"]};line-height:1.6;font-weight:500;">'
                f'3項目以上は高度フレイルリスクとして<br>優先的な保健師介入を推奨します。</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    # ── Tab1 レポートダウンロード ──────────────────────────────────────────
    # A4有効領域: 186mm × 277mm ≈ 703px × 1047px（margin 10mm/12mm）
    # レイアウト: ヘッダー52px + フレイルバー80px + KPIグリッド110px +
    #            レーダー300px + 横棒260px + フッター45px + gaps≒200px = ~1047px
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:11px;font-weight:700;color:{P["muted"]};'
        'letter-spacing:.04em;margin-bottom:4px;">📥 印刷・共有用レポート</div>',
        unsafe_allow_html=True
    )
    # KPIグリッドHTML
    _kpi_grid_html = '<div class="kpi-grid">'
    for _n, _c, _s in unified_kpi:
        _kpi_grid_html += (
            f'<div class="kpi-card" style="--c:{_c["color"]};">'
            f'<div class="icon">{_c["icon"]}</div>'
            f'<div class="name">{_n}</div>'
            f'<div class="pct">{_s["pct"]:.1f}%</div>'
            f'<div class="det">N={_s["n_valid"]}名 ／ リスク{_s["n_risk"]}名</div>'
            f'</div>'
        )
    _kpi_grid_html += '</div>'
    # フレイル判定バー + KPIグリッド
    _hero_sec = f"""
<div class="sec-title">🩺 フレイル判定（簡易フレイルインデックス）</div>
<div class="hero-bar">
  <div class="hero-main">
    <div class="label">フレイル該当率（3点以上）</div>
    <div class="pct">{_hero_pct_frail:.1f}<span style="font-size:16px">%</span></div>
    <div class="sub">{_hero_frail}名 フレイル ／ 判定N={_hero_valid}名</div>
    <div style="background:rgba(255,255,255,.15);border-radius:3px;height:4px;margin-top:8px;">
      <div style="height:4px;border-radius:3px;background:rgba(255,255,255,0.8);
                  width:{min(_hero_pct_frail,100):.1f}%;"></div>
    </div>
  </div>
  <div class="hero-sub">
    <div class="hero-sub-item">
      <div class="label">🟡 プレフレイル</div>
      <div class="pct">{_hero_pct_pre:.1f}%</div>
      <div class="n">{_hero_pre}名</div>
    </div>
    <div class="hero-sub-item green">
      <div class="label">🟢 健常</div>
      <div class="pct">{_hero_pct_normal:.1f}%</div>
      <div class="n">{max(_hero_valid-_hero_frail-_hero_pre,0)}名</div>
    </div>
  </div>
</div>
<div class="sec-title">📊 各指標リスク率サマリー (N={N:,}名)</div>
{_kpi_grid_html}"""
    # A4専用フィギュア生成（width=680px固定, responsive=False）
    _CFG_PRINT = {'responsive': False, 'displayModeBar': False}
    _fig_r_p = go.Figure(fig_r)
    _fig_r_p.update_layout(width=680, height=295,
                           margin=dict(t=45, b=45, l=90, r=90))
    _fig_hb_p = go.Figure(fig_hb)
    _fig_hb_p.update_layout(width=680, height=255,
                             margin=dict(t=20, b=10, l=0, r=100))
    _t1_figs = (
        '<div class="chart-wrap sec-title">📡 フレイル関連指標 リスクマップ</div>'
        + '<div class="chart-wrap">'
        + _fig_r_p.to_html(full_html=False, include_plotlyjs='cdn',
                           config=_CFG_PRINT)
        + '</div>'
        + '<div class="chart-wrap sec-title">📊 指標別リスク該当率（昇順）</div>'
        + '<div class="chart-wrap">'
        + _fig_hb_p.to_html(full_html=False, include_plotlyjs=False,
                             config=_CFG_PRINT)
        + '</div>'
    )
    _t1_html = _make_report_html(
        title='村上市 総合フレイル分析レポート（サマリー）',
        subtitle=f'AWGS2019・WHO基準準拠 ／ フィルター適用後 N={N:,}名 ／ 高齢者支援課向け',
        kpi_rows_html=_hero_sec,
        figs_html=_t1_figs,
        logo_b64=_HAL_LOGO_B64,
    )
    _dl_col1, _ = st.columns([1, 3])
    with _dl_col1:
        st.download_button(
            label='📥 サマリーレポートをダウンロード（印刷用HTML）',
            data=_t1_html.encode('utf-8'),
            file_name='村上市フレイル分析_サマリー.html',
            mime='text/html',
            key='dl_tab1',
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 ─ DETAILED ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    if not avail_names:
        st.info('分析可能な指標データがありません。')
    else:
        st.markdown('<div class="sec">📈 性別・年齢階級別 クロス集計分析</div>',
                    unsafe_allow_html=True)

        _tab2_col1, _tab2_col2 = st.columns([1.6, 1])
        with _tab2_col1:
            sel_flag = st.selectbox(
                '分析指標',
                all_tab_names,
                format_func=lambda x: f'{all_tab_cfg[x]["icon"]} {x}',
            )
        with _tab2_col2:
            show_overall = st.checkbox('全体（合算）も表示', value=False)

        _sel_cfg  = all_tab_cfg[sel_flag]
        flag_col  = _sel_cfg['flag_col']
        base_col  = _sel_cfg['base_col']
        _accent   = _sel_cfg['color']

        def _count_risk(sub_df, _flag_col, _base_col):
            if _base_col:
                _valid = sub_df[_base_col].notna()
            else:
                _valid = sub_df[_flag_col].notna()
            _nv = int(_valid.sum())
            _nr = int(sub_df.loc[_valid, _flag_col].astype(bool).sum()) if _nv > 0 else 0
            return _nv, _nr

        # バタフライチャート（年代 Y軸 / % X軸 / 男性=左 / 女性=右）
        _age_labels_shown, _m_pcts, _f_pcts, _m_ns, _f_ns, _t_pcts, _t_ns = [], [], [], [], [], [], []
        for _ag in AGE_LABELS:
            if '年齢階級' not in df.columns or _ag not in df['年齢階級'].values:
                continue
            _age_labels_shown.append(_ag)
            _age_mask = df['年齢階級'] == _ag
            if '性別_ラベル' in df.columns:
                _m_sub = df[_age_mask & (df['性別_ラベル'] == '男性')]
                _f_sub = df[_age_mask & (df['性別_ラベル'] == '女性')]
            else:
                _m_sub = df[_age_mask].iloc[0:0]  # 空DataFrame（性別なし）
                _f_sub = df[_age_mask].iloc[0:0]
            _t_sub = df[df['年齢階級'] == _ag]
            _mn, _mr = _count_risk(_m_sub, flag_col, base_col)
            _fn, _fr = _count_risk(_f_sub, flag_col, base_col)
            _tn, _tr = _count_risk(_t_sub, flag_col, base_col)
            _m_pcts.append(safe_pct(_mr, _mn)); _m_ns.append(_mn)
            _f_pcts.append(safe_pct(_fr, _fn)); _f_ns.append(_fn)
            _t_pcts.append(safe_pct(_tr, _tn)); _t_ns.append(_tn)

        if not _age_labels_shown:
            st.info('年齢階級データがありません。')
        else:
            _max_pct = max(max(_m_pcts + _f_pcts + [1]), 5)
            _axis_max = min(100, _max_pct * 1.35 + 5)

            # 男女カラー定数（清潔感のあるスチールブルー × ダスティローズ）
            _M_CLR = '#5B95C8'   # スチールブルー（男性）
            _F_CLR = '#C97B9D'   # ダスティローズ（女性）

            fig2 = go.Figure()
            # 男性（左側：負値） テキストはバー内部に配置して他要素とのオーバーラップを防止
            fig2.add_trace(go.Bar(
                name='男性',
                y=_age_labels_shown,
                x=[-p for p in _m_pcts],
                orientation='h',
                marker=dict(color=_M_CLR, opacity=0.90),
                marker_line_width=0,
                text=[f'{p:.1f}%' for p in _m_pcts],
                textposition='inside',
                insidetextanchor='middle',
                textfont=dict(size=11, color='#fff', family='Arial Black, sans-serif'),
                customdata=list(zip(_m_pcts, _m_ns)),
                hovertemplate='<b>男性</b> %{y}<br>リスク率: %{customdata[0]:.1f}%<br>N=%{customdata[1]}名<extra></extra>',
                cliponaxis=True,
            ))
            # 女性（右側：正値）
            fig2.add_trace(go.Bar(
                name='女性',
                y=_age_labels_shown,
                x=_f_pcts,
                orientation='h',
                marker=dict(color=_F_CLR, opacity=0.90),
                marker_line_width=0,
                text=[f'{p:.1f}%' for p in _f_pcts],
                textposition='inside',
                insidetextanchor='middle',
                textfont=dict(size=11, color='#fff', family='Arial Black, sans-serif'),
                customdata=list(zip(_f_pcts, _f_ns)),
                hovertemplate='<b>女性</b> %{y}<br>リスク率: %{customdata[0]:.1f}%<br>N=%{customdata[1]}名<extra></extra>',
                cliponaxis=True,
            ))
            if show_overall:
                fig2.add_trace(go.Scatter(
                    name='全体',
                    y=_age_labels_shown,
                    x=_t_pcts,
                    mode='markers+text',
                    marker=dict(color='#F59E0B', size=10, symbol='diamond',
                                line=dict(color='#fff', width=1.5)),
                    text=[f'{p:.0f}%' for p in _t_pcts],
                    textposition='middle right',
                    textfont=dict(size=10, color='#B45309'),
                    hovertemplate='全体 %{y}: %{x:.1f}%<extra></extra>',
                ))
            # 中心線
            fig2.add_vline(x=0, line_color='#94A3B8', line_width=1.5)
            fig2.update_layout(
                barmode='relative',
                xaxis=dict(
                    range=[-_axis_max, _axis_max],
                    tickvals=[-round(_axis_max*2/3), -round(_axis_max/3), 0,
                               round(_axis_max/3), round(_axis_max*2/3)],
                    ticktext=[f'{round(_axis_max*2/3)}%', f'{round(_axis_max/3)}%', '0%',
                               f'{round(_axis_max/3)}%', f'{round(_axis_max*2/3)}%'],
                    tickfont=dict(size=11, color=P['text']),
                    gridcolor='#E2E8F0',
                    title=dict(text='← 男性    リスク該当率 (%)    女性 →',
                               font=dict(size=12, color=P['text'])),
                    zeroline=True, zerolinecolor='#94A3B8', zerolinewidth=1.5,
                ),
                yaxis=dict(
                    tickfont=dict(size=13, color=P['text']),
                    title=None, autorange='reversed',
                    gridcolor='#F1F5F9',
                ),
                paper_bgcolor='rgba(255,255,255,0.85)', plot_bgcolor='rgba(248,250,252,0.6)',
                font=dict(color=P['text']),
                legend=dict(
                    orientation='h', yanchor='bottom', y=1.02,
                    xanchor='center', x=0.5,
                    font=dict(size=12, color=P['text']),
                    bgcolor='rgba(255,255,255,.9)',
                    bordercolor='rgba(200,214,229,0.6)', borderwidth=1,
                ),
                margin=dict(t=60, b=20, l=10, r=20), height=max(320, len(_age_labels_shown)*68+90),
                title=dict(
                    text=f'{_sel_cfg["icon"]} {sel_flag} ── 性別×年齢階級別 バタフライチャート',
                    font=dict(size=13, color=P['navy'])),
            )
            st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

        # ダブルクロス集計表
        with st.expander('🔍 性別 × 年齢階級 ダブルクロス集計表', expanded=False):
            rows2: List[dict] = []
            for sl in ['男性', '女性']:
                for al in AGE_LABELS:
                    if '性別_ラベル' not in df.columns or '年齢階級' not in df.columns:
                        continue
                    sub   = df[(df['性別_ラベル'] == sl) & (df['年齢階級'] == al)]
                    valid = sub[base_col].notna() if base_col else sub[flag_col].notna()
                    n_v   = int(valid.sum())
                    n_r   = int(sub.loc[valid, flag_col].astype(bool).sum()) if n_v > 0 else 0
                    rows2.append({
                        '性別': sl, '年齢階級': al, 'N': n_v, 'リスク数': n_r,
                        '割合(%)': round(n_r / n_v * 100, 1) if n_v > 0 else None,
                    })
            if rows2:
                st.dataframe(
                    pd.DataFrame(rows2), use_container_width=True, hide_index=True,
                    column_config={
                        '割合(%)': st.column_config.ProgressColumn(
                            '割合(%)', min_value=0, max_value=100, format='%.1f%%'),
                    },
                )

        # 全指標 男女別比較
        if '性別_ラベル' in df.columns:
            st.markdown(
                '<div class="sec" style="margin-top:24px;">📊 全指標 男女別リスク率比較</div>',
                unsafe_allow_html=True
            )
            m_vals, f_vals, i_labels = [], [], []
            for _cname, _ccfg, _ in unified_kpi:
                _cflag = f'flag_{_cname}'
                _cbase = _ccfg.get('col') if _ccfg.get('col') and _ccfg['col'] in df.columns else None
                for sex, lst in [('男性', m_vals), ('女性', f_vals)]:
                    sub = df[df['性別_ラベル'] == sex]
                    if _cbase:
                        _st2 = risk_stats(sub, _cflag, _cbase)
                    else:
                        _st2 = _flag_stats(sub, _cflag)
                    lst.append(_st2['pct'])
                i_labels.append(f'{_ccfg["icon"]} {_cname}')

            fig_cmp = go.Figure()
            fig_cmp.add_trace(go.Bar(
                name='男性', x=i_labels, y=m_vals,
                marker_color='#5B95C8', marker_line_width=0,
                text=[f'{v:.1f}%' for v in m_vals], textposition='outside',
                textfont=dict(size=10, color=P['text']),
            ))
            fig_cmp.add_trace(go.Bar(
                name='女性', x=i_labels, y=f_vals,
                marker_color='#C97B9D', marker_line_width=0,
                text=[f'{v:.1f}%' for v in f_vals], textposition='outside',
                textfont=dict(size=10, color=P['text']),
            ))
            fig_cmp.update_layout(
                barmode='group',
                yaxis=dict(range=[0, 130], ticksuffix='%',
                           gridcolor='#E2E8F0', tickfont=dict(size=10, color=P['text'])),
                xaxis=dict(tickfont=dict(size=10, color=P['text'])),
                paper_bgcolor='rgba(255,255,255,0.88)', plot_bgcolor='rgba(255,255,255,0.7)',
                font=dict(color=P['text']),
                legend=dict(orientation='h', yanchor='bottom', y=1.02,
                            xanchor='right', x=1, font=dict(size=12, color=P['text'])),
                margin=dict(t=50, b=20, l=0, r=0), height=380,
                title=dict(text='全指標 男女別リスク該当率比較',
                           font=dict(size=13, color=P['navy'])),
            )
            st.plotly_chart(fig_cmp, use_container_width=True, config={'displayModeBar': False})

        # ── Tab2 レポートダウンロード ────────────────────────────────────────
        # A4有効領域: 703px × 1047px
        # レイアウト: ヘッダー52px + バタフライ395px + 比較棒グラフ365px +
        #            セクションタイトル×2 44px + gaps+footnote 191px = ~1047px
        st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:11px;font-weight:700;color:{P["muted"]};'
            'letter-spacing:.04em;margin-bottom:4px;">📥 印刷・共有用レポート</div>',
            unsafe_allow_html=True
        )
        _t2_kpi_sec = (
            f'<div class="sec-title">'
            f'{_sel_cfg["icon"]} {sel_flag} ─ 性別×年齢階級別 クロス集計分析</div>'
            f'<p style="font-size:8.5px;color:#526070;margin-bottom:6px;">'
            f'フィルター適用後 N={N:,}名 ／ 簡易フレイルインデックス準拠</p>'
        )
        _CFG2_PRINT = {'responsive': False, 'displayModeBar': False}
        _t2_figs = ''
        # バタフライチャートは年齢データがある場合のみ fig2 が定義されている
        if _age_labels_shown:
            _n_ages = len(_age_labels_shown)
            _fig2_p = go.Figure(fig2)
            _fig2_p.update_layout(width=680, height=max(350, _n_ages * 62 + 90),
                                  margin=dict(t=52, b=18, l=10, r=18))
            _t2_figs = (
                '<div class="chart-wrap">'
                + _fig2_p.to_html(full_html=False, include_plotlyjs='cdn',
                                  config=_CFG2_PRINT)
                + '</div>'
            )
        if '性別_ラベル' in df.columns and 'fig_cmp' in dir():
            _fig_cmp_p = go.Figure(fig_cmp)
            _fig_cmp_p.update_layout(width=680, height=315,
                                     margin=dict(t=42, b=18, l=0, r=0))
            _plotlyjs_mode = False if _t2_figs else 'cdn'
            _t2_figs += (
                '<div class="chart-wrap sec-title">📊 全指標 男女別リスク率比較</div>'
                + '<div class="chart-wrap">'
                + _fig_cmp_p.to_html(full_html=False, include_plotlyjs=_plotlyjs_mode,
                                     config=_CFG2_PRINT)
                + '</div>'
            )
        _t2_html = _make_report_html(
            title=f'村上市 詳細分析レポート ─ {sel_flag}',
            subtitle=f'AWGS2019・WHO基準準拠 ／ フィルター適用後 N={N:,}名',
            kpi_rows_html=_t2_kpi_sec,
            figs_html=_t2_figs,
            logo_b64=_HAL_LOGO_B64,
        )
        _dl2_col, _ = st.columns([1, 3])
        with _dl2_col:
            st.download_button(
                label='📥 詳細分析レポートをダウンロード（印刷用HTML）',
                data=_t2_html.encode('utf-8'),
                file_name=f'村上市フレイル分析_詳細_{sel_flag}.html',
                mime='text/html',
                key='dl_tab2',
            )

        # ── 2指標 相関散布図 ────────────────────────────────────────────────
        st.markdown(
            '<div class="sec" style="margin-top:28px;">🔬 2指標 相関散布図</div>',
            unsafe_allow_html=True
        )

        if len(SCATTER_OPTS) < 2:
            st.info('散布図を表示するには2つ以上の実測値指標データが必要です。')
        else:
            _scat_names = list(SCATTER_OPTS.keys())

            # ── 指標選択 UI（カード形式 2列）──
            st.markdown(f"""
<div style="background:rgba(255,255,255,0.86);backdrop-filter:blur(10px);border-radius:14px;padding:16px 20px;
            box-shadow:0 1px 4px rgba(0,0,0,.07);margin-bottom:16px;">
  <div style="font-size:12px;font-weight:800;color:{P['navy']};margin-bottom:12px;">
    📌 散布図の指標を選択（X軸 / Y軸）</div>""", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            _sc_col1, _sc_col2 = st.columns(2)
            with _sc_col1:
                st.markdown(
                    f'<div style="font-size:11px;font-weight:800;color:{P["navy"]};'
                    f'background:#EFF6FF;border-radius:8px;padding:6px 12px;'
                    f'border-left:4px solid {P["blue"]};margin-bottom:8px;">'
                    '← X軸 指標</div>', unsafe_allow_html=True
                )
                _x_name = st.radio(
                    '', _scat_names, key='scat_x',
                    format_func=lambda n: f'{SCATTER_OPTS[n]["icon"]}  {n}',
                )
            with _sc_col2:
                _y_default_idx = 1 if _scat_names[0] == _x_name else 0
                st.markdown(
                    f'<div style="font-size:11px;font-weight:800;color:{P["navy"]};'
                    f'background:#F0FDF4;border-radius:8px;padding:6px 12px;'
                    f'border-left:4px solid {P["green"]};margin-bottom:8px;">'
                    '↑ Y軸 指標</div>', unsafe_allow_html=True
                )
                _y_name = st.radio(
                    '', _scat_names,
                    index=_y_default_idx,
                    key='scat_y',
                    format_func=lambda n: f'{SCATTER_OPTS[n]["icon"]}  {n}',
                )

            _xc = SCATTER_OPTS[_x_name]
            _yc = SCATTER_OPTS[_y_name]
            _xcol, _ycol = _xc['col'], _yc['col']
            _xflag, _yflag = _xc['flag'], _yc['flag']

            # データ準備
            _sc_df = df[[_xcol, _ycol]].copy()
            _sc_df['xf'] = (df.get(_xflag, pd.Series(False, index=df.index))
                            .fillna(False).astype(bool))
            _sc_df['yf'] = (df.get(_yflag, pd.Series(False, index=df.index))
                            .fillna(False).astype(bool))
            _sc_df = _sc_df.dropna(subset=[_xcol, _ycol])

            _n_sc   = len(_sc_df)
            _n_both = int((_sc_df['xf'] & _sc_df['yf']).sum())
            _n_xo   = int((_sc_df['xf'] & ~_sc_df['yf']).sum())
            _n_yo   = int((~_sc_df['xf'] & _sc_df['yf']).sum())
            _n_none = int((~_sc_df['xf'] & ~_sc_df['yf']).sum())

            if _n_sc == 0:
                st.info('プロット可能なデータがありません。')
            else:
                # 散布図
                fig_sc = go.Figure()
                _sc_groups = [
                    ('正常（両方）',          '#64748B', ~_sc_df['xf'] & ~_sc_df['yf']),
                    (f'{_x_name}のみ',        _xc['color'], _sc_df['xf'] & ~_sc_df['yf']),
                    (f'{_y_name}のみ',        _yc['color'], ~_sc_df['xf'] & _sc_df['yf']),
                    ('両方リスク',            '#DC2626', _sc_df['xf'] & _sc_df['yf']),
                ]
                for _lbl, _clr, _mask in _sc_groups:
                    _sub = _sc_df[_mask]
                    if len(_sub) == 0:
                        continue
                    fig_sc.add_trace(go.Scatter(
                        x=_sub[_xcol], y=_sub[_ycol],
                        mode='markers',
                        name=f'{_lbl}（{len(_sub)}名）',
                        marker=dict(
                            color=_clr, size=8, opacity=0.72,
                            line=dict(color='white', width=0.8),
                        ),
                        hovertemplate=(
                            f'<b>{_x_name}</b>: %{{x:.2f}}<br>'
                            f'<b>{_y_name}</b>: %{{y:.2f}}'
                            f'<extra>{_lbl}</extra>'
                        ),
                    ))

                # 閾値ライン
                if _xc.get('val') is not None:
                    fig_sc.add_vline(
                        x=_xc['val'], line_color=_xc['color'],
                        line_width=1.8, line_dash='dash',
                        annotation=dict(
                            text=f'X閾値 {_xc["val"]}',
                            font=dict(size=10, color=_xc['color']),
                            bgcolor='rgba(255,255,255,.85)',
                        ),
                    )
                if _yc.get('val') is not None:
                    fig_sc.add_hline(
                        y=_yc['val'], line_color=_yc['color'],
                        line_width=1.8, line_dash='dash',
                        annotation=dict(
                            text=f'Y閾値 {_yc["val"]}',
                            font=dict(size=10, color=_yc['color']),
                            bgcolor='rgba(255,255,255,.85)',
                        ),
                    )

                fig_sc.update_layout(
                    paper_bgcolor='rgba(255,255,255,0.88)', plot_bgcolor='rgba(248,250,252,0.6)',
                    font=dict(color=P['text']),
                    xaxis=dict(
                        title=dict(
                            text=f'{_xc["icon"]} {_x_name}',
                            font=dict(size=12, color=P['text'])
                        ),
                        gridcolor='#E2E8F0',
                        tickfont=dict(size=10, color=P['text']),
                    ),
                    yaxis=dict(
                        title=dict(
                            text=f'{_yc["icon"]} {_y_name}',
                            font=dict(size=12, color=P['text'])
                        ),
                        gridcolor='#E2E8F0',
                        tickfont=dict(size=10, color=P['text']),
                    ),
                    legend=dict(
                        orientation='h', yanchor='bottom', y=1.02,
                        xanchor='right', x=1,
                        font=dict(size=11, color=P['text']),
                        bgcolor='rgba(255,255,255,.9)',
                        bordercolor='#E2E8F0', borderwidth=1,
                    ),
                    margin=dict(t=55, b=20, l=0, r=0), height=480,
                    title=dict(
                        text=f'フィルター適用 N={_n_sc:,}名（欠損除外）',
                        font=dict(size=11, color=P['muted']), x=0.5,
                    ),
                )
                st.plotly_chart(fig_sc, use_container_width=True,
                                config={'displayModeBar': False})

                # ── 象限別 集計カード ──
                _stat_items = [
                    ('#64748B', _n_none,  '正常（両方）',       safe_pct(_n_none,  _n_sc)),
                    (_xc['color'],  _n_xo,   f'{_x_name}のみ', safe_pct(_n_xo,   _n_sc)),
                    (_yc['color'],  _n_yo,   f'{_y_name}のみ', safe_pct(_n_yo,   _n_sc)),
                    ('#DC2626', _n_both, '両方リスク',          safe_pct(_n_both, _n_sc)),
                ]
                _stat_cols = st.columns(4)
                for _si, (_sclr, _sn, _slbl, _spct) in enumerate(_stat_items):
                    with _stat_cols[_si]:
                        st.markdown(f"""
<div style="background:rgba(255,255,255,0.86);backdrop-filter:blur(10px);border-radius:12px;padding:14px 12px;
            box-shadow:0 1px 4px rgba(0,0,0,.08);border-top:4px solid {_sclr};
            text-align:center;">
  <div style="font-size:30px;font-weight:800;color:{_sclr};line-height:1.1;">{_sn}</div>
  <div style="font-size:10px;font-weight:700;color:{P['muted']};margin-top:3px;
              line-height:1.4;">{_slbl}</div>
  <div style="font-size:20px;font-weight:700;color:{_sclr};margin-top:4px;">{_spct:.1f}%</div>
  <div style="background:#E2E8F0;border-radius:3px;height:4px;margin-top:8px;">
    <div style="height:4px;border-radius:3px;background:{_sclr};
                width:{min(_spct,100):.1f}%;"></div>
  </div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 ─ FOLLOW-UP LIST
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div class="sec red">🚨 高リスク対象者抽出（フォローアップ優先順）</div>',
                unsafe_allow_html=True)

    if 'リスク重複数' not in df.columns:
        st.warning('リスク重複数が算出できませんでした。データを確認してください。')
    else:
        col_c1, col_c2 = st.columns([1, 2])
        with col_c1:
            min_risk = st.slider('最低リスク重複数（項目数）', 1, 6, 2)
        with col_c2:
            flag_filter = st.multiselect(
                '特定リスクで絞り込み（空欄 = 制限なし）',
                all_tab_names,
                format_func=lambda x: f'{all_tab_cfg[x]["icon"]} {x}',
            )

        det = df[df['リスク重複数'] >= min_risk].copy()
        for fl in flag_filter:
            fc_col = f'flag_{fl}'
            if fc_col in det.columns:
                det = det[det[fc_col].fillna(False).astype(bool)]
        det = det.sort_values('リスク重複数', ascending=False)

        # 全指標（unified_kpi）のフラグ列を表示名にマッピング
        _short_names = {
            'フレイル判定': 'フレイル', '下肢筋力低下': '筋力↓', '歩行速度低下': '歩行↓',
            'バランス能力低下': 'バランス↓', 'サルコペニア疑い': 'サルコ?',
            'オーラルフレイル': '口腔FL', 'MCI疑い': 'MCI', '嚥下機能低下リスク': '嚥下↓',
            '骨密度低下': '骨密度↓', 'サルコペニア確定': 'AWGS確定',
        }
        flag_disp: Dict[str, str] = {}
        for _fn, _, _ in unified_kpi:
            _fc = f'flag_{_fn}'
            if _fc in det.columns:
                flag_disp[_fc] = _short_names.get(_fn, _fn[:5])
        # 追加フラグ
        for _fc, _disp in [('flag_握力低下', '握力↓'), ('flag_プレフレイル判定', 'プレFL'),
                            ('flag_AWGS2019サルコペニア', 'AWGS2019')]:
            if _fc in det.columns and _fc not in flag_disp:
                flag_disp[_fc] = _disp

        show_flags = {k: v for k, v in flag_disp.items() if k in det.columns}
        num_disp   = [c for c in ['歩行速度_mps', '5回立ち上がり_秒', 'MoCA総得点',
                                   'SMI', 'Tスコア_SD', 'EAT10総得点']
                      if c in det.columns]

        base_cols: List[str] = ['ID']
        if '性別_ラベル' in det.columns: base_cols.append('性別_ラベル')
        if '年齢' in det.columns:        base_cols.append('年齢')
        if '年齢階級' in det.columns:    base_cols.append('年齢階級')

        show_c = base_cols + list(show_flags.keys()) + num_disp + ['リスク重複数']
        show_c = [c for c in show_c if c in det.columns]

        det_show = det[show_c].rename(
            columns={'性別_ラベル': '性別', **show_flags}
        ).copy()
        for sh in show_flags.values():
            if sh in det_show.columns:
                det_show[sh] = (
                    det_show[sh]
                    .map({True: '🔴', False: '✅', 1: '🔴', 0: '✅', 1.0: '🔴', 0.0: '✅'})
                    .fillna('—')
                )

        n_det   = len(det_show)
        pct_det = safe_pct(n_det, N)

        st.markdown(f"""
        <div class="alert">
          <span class="alert-n">{n_det:,} 名</span>
          <span class="alert-sub">（対象 {N}名中 {pct_det:.1f}%）に
            {min_risk}項目以上のリスクが重複</span>
          <div class="alert-tip">🔔 架電・文書勧奨など保健師による優先フォローアップを推奨</div>
        </div>
        """, unsafe_allow_html=True)

        if n_det > 0:
            col_cfg: dict = {
                'ID':          st.column_config.NumberColumn('ID', format='%d', width='small'),
                'リスク重複数': st.column_config.NumberColumn('重複数', format='%d 項目', width='small'),
            }
            for orig, (label, fmt) in {
                '歩行速度_mps':     ('歩行速度(m/s)', '%.3f'),
                '5回立ち上がり_秒': ('STS(秒)',        '%.1f'),
                'MoCA総得点':       ('MoCA',          '%.0f'),
                'SMI':              ('SMI',            '%.2f'),
                'Tスコア_SD':       ('T-score',        '%.2f'),
                'EAT10総得点':      ('EAT-10',         '%.0f'),
            }.items():
                if orig in det_show.columns:
                    col_cfg[orig] = st.column_config.NumberColumn(label, format=fmt)
            for sh in show_flags.values():
                if sh in det_show.columns:
                    col_cfg[sh] = st.column_config.TextColumn(sh, width='small')

            st.dataframe(
                det_show, use_container_width=True,
                height=min(540, 56 + 36 * n_det),
                column_config=col_cfg, hide_index=True,
            )

            dl_df     = det[show_c].rename(columns={'性別_ラベル': '性別'})
            csv_bytes = dl_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                label=f'⬇️  高リスク対象者リスト（{n_det}名）をCSVダウンロード',
                data=csv_bytes,
                file_name='高リスク対象者リスト_2025村上市_フレイル分析.csv',
                mime='text/csv',
            )
        else:
            st.info('該当する対象者がいません。フィルター条件を緩めてください。')


# ─── フッター ──────────────────────────────────────────────────────────────────
st.divider()
with st.expander('📐 判定基準・エビデンスソース一覧', expanded=False):
    st.markdown("""
| 指標 | カットオフ | エビデンス |
|---|---|---|
| 歩行速度低下 | < 1.0 m/s | AWGS 2019 |
| 下肢筋力低下 | 5回STS ≥ 12秒 | SPPB準拠 |
| サルコペニア疑い | SMI < 7.0（男）/ < 5.7（女）kg/m² | AWGS2019 |
| サルコペニア確定 | 低SMI ＋ 低歩行速度または低STS | AWGS2019 複合診断 |
| 骨密度低下 | Tスコア ≤ −1.0 SD | WHO 1994 / 日本骨粗鬆症学会 |
| MCI疑い | MoCA ≤ 25点 | Nasreddine et al., JAGS 2005 |
| 嚥下機能低下リスク | EAT-10 ≥ 3点 | Belafsky et al., Ann Otol 2008 |
| フレイル判定 | 簡易フレイルインデックス ≥3点（5項目合計） | 田中友規ら / 飯島勝矢ら 簡易フレイルインデックス |
| オーラルフレイル | 口腔機能質問紙 ≥1点（咀嚼・ディアドコ等） | 飯島勝矢ら 2014 |
| バランス能力低下 | SPPB バランス < 4点 | Guralnik et al. 1994 |

> **免責**: 本ダッシュボードはスクリーニング目的です。臨床診断を代替するものではありません。簡易フレイルインデックスの各項目の方向性（高値=リスク）について、データ収集時の入力定義に合わせて確認してください。
""")
st.caption(
    'AWGS2019 / WHO 1994 / Nasreddine 2005 / Belafsky 2008 / J-CHS 2020 準拠 ｜ '
    '村上市 高齢者支援課・保健師・行政幹部向けスクリーニングツール'
)
