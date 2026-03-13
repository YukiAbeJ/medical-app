#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
村上市 高齢者総合検診 2025 - 静的ダッシュボード生成スクリプト
実データ埋め込み型HTML（PC不要・GitHub Pages永続公開対応）
"""
import pandas as pd
import numpy as np
import json, glob, io, re, os, warnings

warnings.filterwarnings('ignore')

HERE      = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS = os.path.join(os.path.expanduser('~'), 'Downloads')

# ── CSV読み込みユーティリティ ──
def read_csv_smart(path):
    for enc in ['utf-8-sig', 'cp932', 'utf-8']:
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, low_memory=False)
            def clean_col(c):
                parts = [p.strip() for p in str(c).split('\n') if p.strip()]
                return '_'.join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else str(c))
            df.columns = [clean_col(c) for c in df.columns]
            df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]
            non_un = [c for c in df.columns if not str(c).startswith('Unnamed:')]
            if non_un and (sum(bool(re.match(r'^[\d\s.]+$', str(c).strip())) for c in non_un) / len(non_un) > 0.85):
                df = pd.read_csv(io.BytesIO(raw), encoding=enc, header=1, low_memory=False)
                df.columns = [clean_col(c) for c in df.columns]
                df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]
            df = df.loc[:, ~df.columns.duplicated(keep='first')]
            if len(df) > 0:
                return df
        except Exception:
            continue
    return None

def normalize_id_col(df):
    cands = [c for c in df.columns if re.search(r'\bID\b|^ID_|_ID$', str(c), re.IGNORECASE) or str(c).strip().lower() == 'id']
    if not cands:
        cands = [c for c in df.columns if re.search(r'\.?\s*ID\s*$', str(c), re.IGNORECASE)]
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

def find_csv(keywords, exclude=None):
    for f in sorted(glob.glob(os.path.join(DOWNLOADS, '*.csv'))):
        name = os.path.basename(f)
        if all(k in name for k in keywords):
            if exclude and any(k in name for k in exclude):
                continue
            return f
    return None

# ── メインデータ読み込み ──
df1 = pd.read_csv(os.path.join(HERE, '01_クリーニング済みマスターデータ_1.csv'), encoding='utf-8-sig')
df2_path = os.path.join(HERE, 'Cleaned_2025村上検診結果_Binary_20260227.csv')
if os.path.exists(df2_path):
    df2 = pd.read_csv(df2_path, encoding='utf-8-sig')
    df2 = df2.rename(columns={'ID_下4桁': 'ID'})
    df  = df1.merge(df2, on='ID', how='left')
else:
    df = df1.copy()
    print("警告: Binary CSVが見つかりません")

for c in df.columns[1:]:
    df[c] = pd.to_numeric(df[c], errors='coerce')

df['sx'] = df['性別'].map({1: '男性', 0: '女性'})
bins = [0, 64, 69, 74, 79, 200]
labs = ['65歳未満', '65-69歳', '70-74歳', '75-79歳', '80歳以上']
df['ag'] = pd.cut(df['年齢'], bins=bins, labels=labs, right=True).astype(str)
smi = pd.to_numeric(df['SMI'], errors='coerce')

def fl(col, op, val):
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = pd.to_numeric(df[col], errors='coerce')
    if op == '<':    r = s < val
    elif op == '<=': r = s <= val
    elif op == '>=': r = s >= val
    else: return pd.Series(False, index=df.index)
    return r.where(s.notna()).fillna(False).astype(bool)

# 既存6指標フラグ
df['fw'] = fl('歩行速度_mps',     '<',  1.0)
df['fs'] = fl('5回立ち上がり_秒', '>=', 12.0)
df['fb'] = fl('Tスコア_SD',       '<=', -1.0)
df['fm'] = fl('MoCA総得点',       '<=', 25)
df['fe'] = fl('EAT10総得点',      '>=', 3)
df['fa'] = (
    ((df['sx'] == '男性') & (smi < 7.0)) |
    ((df['sx'] == '女性') & (smi < 5.7))
).fillna(False)

# ── SPPB (バランス得点) ──
sppb_path = find_csv(['SPPB'])
if sppb_path:
    print(f"SPPB: {os.path.basename(sppb_path)}")
    df_sppb = read_csv_smart(sppb_path)
    df_sppb2 = normalize_id_col(df_sppb) if df_sppb is not None else None
    if df_sppb2 is not None:
        bal_col = next((c for c in df_sppb2.columns if 'バランス' in c and '得点' in c), None)
        if bal_col:
            tmp = df_sppb2[['ID', bal_col]].rename(columns={bal_col: 'バランス_得点'})
            tmp = tmp.drop_duplicates(subset=['ID'], keep='first')
            df = df.merge(tmp, on='ID', how='left')
            print(f"  バランス_得点: {df['バランス_得点'].notna().sum()}名有効, 分布={dict(df['バランス_得点'].value_counts().sort_index())}")
        else:
            print(f"  警告: バランス_得点列なし。列={list(df_sppb2.columns[:8])}")
    else:
        print("  警告: ID列の正規化に失敗")
else:
    print("警告: SPPB CSVが見つかりません")

# ── オーラルフレイル（総合点列を持つファイルを検索）──
oral_found = False
for f in sorted(glob.glob(os.path.join(DOWNLOADS, '*.csv'))):
    df_oral = read_csv_smart(f)
    if df_oral is None:
        continue
    oral_col = next((c for c in df_oral.columns if '総合点' in c and len(df_oral) > 100), None)
    if oral_col is None:
        continue
    df_oral2 = normalize_id_col(df_oral)
    if df_oral2 is None:
        continue
    tmp = df_oral2[['ID', oral_col]].rename(columns={oral_col: 'オーラルフレイル_総合点'})
    tmp = tmp.drop_duplicates(subset=['ID'], keep='first')
    df = df.merge(tmp, on='ID', how='left')
    print(f"オーラルフレイル: {os.path.basename(f)}")
    print(f"  総合点列: {oral_col}, 有効={df['オーラルフレイル_総合点'].notna().sum()}名")
    oral_found = True
    break
if not oral_found:
    print("警告: オーラルフレイル CSVが見つかりません")

# ── J-CHSフレイル判定 ──
FRAIL_ITEM_COLS = [
    ('activity', '軽い運動plus定期的運動_0_1'),
    ('weight',   '6ヵ月体重減少_0_1'),
    ('fatigue',  '訳もなく疲れたように感じる_0_1'),
    ('walk',     '4m歩行_1_0_値'),
    ('grip',     '握力_0_1_値'),
]
jchs_path = find_csv(['フレイル判定'], exclude=['オーラル'])
if jchs_path:
    print(f"J-CHS: {os.path.basename(jchs_path)}")
    df_jchs = read_csv_smart(jchs_path)
    df_jchs2 = normalize_id_col(df_jchs) if df_jchs is not None else None
    if df_jchs2 is not None:
        avail_cols = [col for _, col in FRAIL_ITEM_COLS if col in df_jchs2.columns]
        keep = ['ID'] + avail_cols
        tmp = df_jchs2[keep].drop_duplicates(subset=['ID'], keep='first')
        df = df.merge(tmp, on='ID', how='left')
        print(f"  J-CHS項目検出: {avail_cols}")
    else:
        print("  警告: ID列の正規化に失敗")
        avail_cols = []
else:
    print("警告: フレイル判定 CSVが見つかりません")
    avail_cols = []

# J-CHSスコア計算（5項目合計、活動列は0=低活動=フレイル点）
act_col = '軽い運動plus定期的運動_0_1'
avail_jchs = [col for _, col in FRAIL_ITEM_COLS if col in df.columns]
if len(avail_jchs) >= 3:
    scores  = pd.Series(0.0, index=df.index)
    counted = pd.Series(0,   index=df.index)
    for col in avail_jchs:
        v = pd.to_numeric(df[col], errors='coerce')
        has_val = v.notna()
        counted += has_val.astype(int)
        if col == act_col:
            scores += (v == 0).astype(float).where(has_val, 0.0)
        else:
            scores += (v >= 1).astype(float).where(has_val, 0.0)
    valid_mask     = counted >= 3
    df['jchs_score'] = scores.where(valid_mask)
    df['ffrail']     = (df['jchs_score'] >= 3).fillna(False).astype(bool)
    n_valid = int(df['jchs_score'].notna().sum())
    n_frail = int(df['ffrail'].sum())
    print(f"J-CHSフレイル({len(avail_jchs)}/5項目使用): {n_frail}/{n_valid}名 = {n_frail/max(n_valid,1)*100:.1f}%")
else:
    df['jchs_score'] = np.nan
    df['ffrail']     = pd.Series(False, index=df.index)
    print(f"警告: J-CHS項目不足 ({len(avail_jchs)}/5)")

# 追加指標フラグ
df['fbal']  = fl('バランス_得点', '<', 4)
df['foral'] = fl('オーラルフレイル_総合点', '>=', 1)

# ── リスク重複数（9指標）──
df['risks'] = df[['fw','fs','fa','fb','fm','fe','fbal','foral','ffrail']].astype(int).sum(axis=1)

def fv(v):
    if v is None: return None
    if isinstance(v, float) and np.isnan(v): return None
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating): return round(float(v), 3)
    return v

# ── 患者レコード生成 ──
records = []
for _, r in df.iterrows():
    records.append({
        'id':     fv(r['ID']),
        'sx':     r['sx'] if pd.notna(r.get('sx')) else None,
        'age':    fv(r['年齢']),
        'ag':     r['ag'] if r['ag'] != 'nan' else None,
        'h':      fv(r.get('身長_cm')),
        'w':      fv(r.get('体重_kg')),
        'bmi':    fv(r.get('BMI')),
        'fat':    fv(r.get('体脂肪率')),
        'mus':    fv(r.get('骨格筋量_kg')),
        'smi':    fv(r.get('SMI')),
        'w1':     fv(r.get('歩行速度_mps')),
        'w2':     fv(r.get('歩行速度_mps_2回目')),
        'sts':    fv(r.get('5回立ち上がり_秒')),
        'moca':   fv(r.get('MoCA総得点')),
        'eat':    fv(r.get('EAT10総得点')),
        'ts':     fv(r.get('Tスコア_SD')),
        'tp':     fv(r.get('Tスコア_%')),
        'sos':    fv(r.get('SOS')),
        'bua':    fv(r.get('BUA')),
        'osi':    fv(r.get('OSI')),
        'bf':     fv(r.get('評価用紙')),
        'bs':     fv(r.get('SPPB')),
        'be':     fv(r.get('Eat-10')),
        'bm':     fv(r.get('Moca')),
        'bi':     fv(r.get('Inbody')),
        'bb':     fv(r.get('骨密度')),
        'bal':    fv(r.get('バランス_得点')),
        'oral':   fv(r.get('オーラルフレイル_総合点')),
        'jchs':   fv(r.get('jchs_score')),
        'fw':     int(r['fw']),
        'fs':     int(r['fs']),
        'fa':     int(r['fa']),
        'fb':     int(r['fb']),
        'fm':     int(r['fm']),
        'fe':     int(r['fe']),
        'fbal':   int(r['fbal']),
        'foral':  int(r['foral']),
        'ffrail': int(r['ffrail']),
        'risks':  int(r['risks']),
    })

N  = len(records)
NM = int((df['sx'] == '男性').sum())
NF = int((df['sx'] == '女性').sum())

# ── KPI統計 ──
def kpi(flag_key, base_col):
    valid = int(df[base_col].notna().sum()) if base_col in df.columns else N
    risk  = int(df[flag_key].sum())
    pct   = round(risk / valid * 100, 1) if valid > 0 else 0.0
    return {'risk': risk, 'safe': valid - risk, 'valid': valid, 'pct': pct}

KPI = {
    'walk':   kpi('fw',     '歩行速度_mps'),
    'sts':    kpi('fs',     '5回立ち上がり_秒'),
    'sarco':  kpi('fa',     'SMI'),
    'bone':   kpi('fb',     'Tスコア_SD'),
    'mci':    kpi('fm',     'MoCA総得点'),
    'eat':    kpi('fe',     'EAT10総得点'),
    'bal':    kpi('fbal',   'バランス_得点'),
    'oral':   kpi('foral',  'オーラルフレイル_総合点'),
    'frail':  kpi('ffrail', 'jchs_score'),
}

# ── 検査実施状況 ──
BIN = {}
for key, col in [('form','評価用紙'),('sppb','SPPB'),('eat10','Eat-10'),
                 ('moca','Moca'),('inbody','Inbody'),('bone_d','骨密度')]:
    n = int(df[col].fillna(0).astype(int).sum()) if col in df.columns else 0
    BIN[key] = {'n': n, 'pct': round(n / N * 100, 1)}

# ── 年代別リスク ──
AGE_LABS = ['65歳未満', '65-69歳', '70-74歳', '75-79歳', '80歳以上']
FLAG_INFO = [
    ('fw',     '歩行速度_mps'),
    ('fs',     '5回立ち上がり_秒'),
    ('fa',     'SMI'),
    ('fb',     'Tスコア_SD'),
    ('fm',     'MoCA総得点'),
    ('fe',     'EAT10総得点'),
    ('fbal',   'バランス_得点'),
    ('foral',  'オーラルフレイル_総合点'),
    ('ffrail', 'jchs_score'),
]
age_kpi = {}
for ag in AGE_LABS:
    sub = df[df['ag'] == ag]
    age_kpi[ag] = {'n': len(sub)}
    for fk, fc in FLAG_INFO:
        v = int(sub[fc].notna().sum()) if fc in sub.columns else 0
        r = int(sub[fk].sum())
        age_kpi[ag][fk] = round(r / v * 100, 1) if v > 0 else 0.0

# ── リスク重複分布 ──
RISK_DIST = {}
for k in range(10):
    RISK_DIST[str(k)] = int((df['risks'] == k).sum())

DATA_JS = json.dumps({
    'records': records,
    'N': N, 'NM': NM, 'NF': NF,
    'KPI': KPI,
    'BIN': BIN,
    'age_kpi': age_kpi,
    'risk_dist': RISK_DIST,
}, ensure_ascii=False, separators=(',', ':'))

print(f"\n{'='*50}")
print(f"records={N}, JSON={len(DATA_JS)//1024}KB")
print(f"リスク分布: { {k:v for k,v in RISK_DIST.items() if v>0} }")
n3 = sum(v for k,v in RISK_DIST.items() if int(k)>=3)
n4 = sum(v for k,v in RISK_DIST.items() if int(k)>=4)
print(f"risks>=3: {n3}名 ({n3/N*100:.1f}%), risks>=4: {n4}名 ({n4/N*100:.1f}%)")
print(f"{'='*50}")

# ── HTML生成 ──
html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>村上市 高齢者総合検診 2025 フレイル分析ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Hiragino Sans','Yu Gothic','Meiryo',sans-serif;background:#F1F5F9;color:#1E293B;font-size:14px}}
::-webkit-scrollbar{{width:5px;height:5px}}
::-webkit-scrollbar-thumb{{background:#94A3B8;border-radius:10px}}
#header{{background:linear-gradient(135deg,#1E3A5F 0%,#2563EB 100%);padding:16px 28px;display:flex;align-items:center;gap:16px;box-shadow:0 2px 12px rgba(0,0,0,.18);position:sticky;top:0;z-index:100}}
#header h1{{color:#fff;font-size:18px;font-weight:800;letter-spacing:.01em;line-height:1.3}}
#header .sub{{color:rgba(255,255,255,.78);font-size:11px;margin-top:3px;font-weight:500}}
#wrap{{display:flex;min-height:calc(100vh - 56px)}}
#sidebar{{width:220px;flex-shrink:0;background:#fff;border-right:1px solid #E2E8F0;padding:18px 14px;overflow-y:auto}}
#main{{flex:1;padding:20px 22px;overflow-x:hidden}}
.sb-title{{font-size:11px;font-weight:800;color:#1E3A5F;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid #2563EB;padding-bottom:5px;margin-bottom:12px}}
.sb-group{{margin-bottom:18px}}
.sb-label{{font-size:11.5px;font-weight:700;color:#475569;margin-bottom:7px}}
.chk-item{{display:flex;align-items:center;gap:7px;margin-bottom:5px;cursor:pointer}}
.chk-item input{{accent-color:#2563EB;cursor:pointer}}
.chk-item span{{font-size:12.5px;color:#1E293B;font-weight:500}}
.sb-stat{{background:#F8FAFC;border-radius:8px;padding:10px 12px;font-size:12px;color:#475569;margin-top:4px;line-height:1.7}}
.sb-stat b{{color:#1E3A5F}}
.sec-head{{font-size:13.5px;font-weight:800;color:#1E3A5F;border-left:4px solid #2563EB;padding:2px 0 2px 12px;margin:24px 0 14px;display:flex;align-items:center;gap:6px}}
.sec-head.red{{border-left-color:#DC2626;color:#7F1D1D}}
.sec-head.gray{{border-left-color:#94A3B8;color:#64748B}}
.sec-head.green{{border-left-color:#059669;color:#065F46}}
.sec-head.teal{{border-left-color:#0891B2;color:#164E63}}
.kpi-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:4px}}
.kpi-grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:4px}}
@media(max-width:1100px){{.kpi-grid{{grid-template-columns:repeat(3,1fr)}}.kpi-grid3{{grid-template-columns:repeat(3,1fr)}}}}
.kpi-card{{background:#fff;border-radius:12px;padding:14px 12px 12px;box-shadow:0 1px 3px rgba(0,0,0,.07),0 3px 12px rgba(0,0,0,.05);border-top:4px solid var(--ac);height:100%}}
.kpi-icon{{font-size:20px;margin-bottom:4px}}
.kpi-name{{font-size:10px;font-weight:700;color:#475569;letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px;min-height:28px}}
.kpi-pct{{font-size:32px;font-weight:800;color:var(--ac);line-height:1}}
.kpi-unit{{font-size:13px;color:#475569;font-weight:500}}
.kpi-detail{{font-size:11px;color:#475569;margin-top:4px;font-weight:500}}
.kpi-bar-bg{{background:#E2E8F0;border-radius:4px;height:5px;margin-top:9px;overflow:hidden}}
.kpi-bar-fill{{height:5px;border-radius:4px;background:var(--ac)}}
.kpi-basis{{font-size:9.5px;color:#64748B;margin-top:6px;line-height:1.45}}
.bin-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}}
@media(max-width:1100px){{.bin-grid{{grid-template-columns:repeat(3,1fr)}}}}
.bin-card{{background:#fff;border-radius:12px;padding:14px 12px;box-shadow:0 1px 3px rgba(0,0,0,.07);border-top:4px solid var(--ac)}}
.bin-n{{font-size:28px;font-weight:800;color:var(--ac);line-height:1}}
.bin-pct{{font-size:11.5px;color:#475569;margin-top:3px;font-weight:600}}
.bin-lbl{{font-size:9px;color:#64748B;margin-top:8px}}
.risk-sub{{margin-top:8px;padding:6px 8px;border-radius:6px;background:var(--ac-bg);border-left:3px solid var(--ac)}}
.risk-sub-pct{{font-size:17px;font-weight:800;color:var(--ac)}}
.risk-sub-lbl{{font-size:9.5px;color:var(--ac);font-weight:700}}
.chart-grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}}
@media(max-width:900px){{.chart-grid-2{{grid-template-columns:1fr}}}}
.chart-card{{background:#fff;border-radius:12px;padding:18px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
.chart-title{{font-size:12px;font-weight:700;color:#1E3A5F;margin-bottom:14px}}
.alert-box{{background:#FEF2F2;border:1.5px solid #FECACA;border-left:4px solid #DC2626;border-radius:10px;padding:14px 18px;margin-bottom:14px}}
.alert-n{{font-size:28px;font-weight:800;color:#991B1B}}
.alert-sub{{font-size:13px;color:#7F1D1D;font-weight:500;margin-left:8px}}
.alert-tip{{font-size:11px;color:#B91C1C;margin-top:4px}}
.tbl-wrap{{overflow-x:auto;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:12px}}
thead th{{background:#1E3A5F;color:#fff;padding:10px 8px;text-align:center;font-weight:700;font-size:11px;white-space:nowrap;position:sticky;top:0}}
thead th:first-child{{border-radius:10px 0 0 0}}
thead th:last-child{{border-radius:0 10px 0 0}}
tbody tr:nth-child(even){{background:#F8FAFC}}
tbody tr:hover{{background:#EFF6FF}}
tbody td{{padding:8px 8px;text-align:center;color:#1E293B;border-bottom:1px solid #F1F5F9;white-space:nowrap}}
tbody td.risk-flag-yes{{color:#DC2626;font-weight:700}}
tbody td.risk-flag-no{{color:#94A3B8}}
#filter-info{{background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;padding:8px 14px;font-size:12px;color:#1E40AF;margin-bottom:14px;font-weight:600}}
.risk-badge-0{{background:#DCFCE7;color:#166534;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700}}
.risk-badge-1{{background:#FEF9C3;color:#854D0E;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700}}
.risk-badge-2{{background:#FFEDD5;color:#9A3412;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700}}
.risk-badge-3{{background:#FEE2E2;color:#991B1B;border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700}}
@media(max-width:768px){{#sidebar{{display:none}}.kpi-grid,.bin-grid,.kpi-grid3{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>

<div id="header">
  <div style="font-size:32px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.3))">🏥</div>
  <div style="flex:1">
    <div style="font-size:18px;font-weight:800;color:#fff;letter-spacing:.01em">村上市 高齢者総合検診 2025年度 — フレイル分析ダッシュボード</div>
    <div style="font-size:11px;color:rgba(255,255,255,.78);margin-top:3px">AWGS2019・J-CHS・WHO基準準拠 ／ 9指標総合評価 ／ 高齢者支援課・保健師・行政幹部向け</div>
  </div>
  <div style="background:rgba(255,255,255,.14);border-radius:10px;padding:10px 18px;text-align:right;flex-shrink:0">
    <div style="color:#fff;font-size:26px;font-weight:800;line-height:1" id="hdr-n">{N}</div>
    <div style="color:rgba(255,255,255,.80);font-size:11px;margin-top:2px" id="hdr-sub">男性{NM}名 ／ 女性{NF}名</div>
  </div>
</div>

<div id="wrap">
<div id="sidebar">
  <div class="sb-title">データフィルター</div>
  <div class="sb-group">
    <div class="sb-label">性別</div>
    <label class="chk-item"><input type="checkbox" value="男性" checked onchange="applyFilter()"><span>男性</span></label>
    <label class="chk-item"><input type="checkbox" value="女性" checked onchange="applyFilter()"><span>女性</span></label>
  </div>
  <div class="sb-group">
    <div class="sb-label">年齢階級</div>
    <label class="chk-item"><input type="checkbox" value="65歳未満" checked onchange="applyFilter()"><span>65歳未満</span></label>
    <label class="chk-item"><input type="checkbox" value="65-69歳" checked onchange="applyFilter()"><span>65-69歳</span></label>
    <label class="chk-item"><input type="checkbox" value="70-74歳" checked onchange="applyFilter()"><span>70-74歳</span></label>
    <label class="chk-item"><input type="checkbox" value="75-79歳" checked onchange="applyFilter()"><span>75-79歳</span></label>
    <label class="chk-item"><input type="checkbox" value="80歳以上" checked onchange="applyFilter()"><span>80歳以上</span></label>
  </div>
  <div class="sb-group">
    <div class="sb-label">最低リスク重複数</div>
    <div style="display:flex;align-items:center;gap:8px">
      <input type="range" id="min-risk" min="1" max="9" value="3" style="flex:1;accent-color:#2563EB" oninput="document.getElementById('min-risk-val').textContent=this.value;renderHighRisk()">
      <span id="min-risk-val" style="font-size:13px;font-weight:700;color:#1E3A5F;min-width:16px">3</span>
    </div>
    <div style="font-size:10.5px;color:#64748B;margin-top:4px">項目以上をリスト表示</div>
  </div>
  <div class="sb-stat" id="sb-stat-box">
    対象: <b id="sb-n">{N}</b>名<br>
    男性: <b id="sb-m">{NM}</b>名 ／ 女性: <b id="sb-f">{NF}</b>名<br>
    4項目以上: <b id="sb-r4">-</b>名
  </div>
</div>

<div id="main">
  <div id="filter-info">フィルター適用中: 全{N}名 ／ 全年齢 ／ 全性別</div>

  <!-- 身体機能6指標 -->
  <div class="sec-head">📊 身体機能リスク指標（欠損値除外・実測ベース）</div>
  <div class="kpi-grid" id="kpi-grid"></div>

  <!-- フレイル・追加3指標 -->
  <div class="sec-head teal">🔍 フレイル・口腔・バランス指標</div>
  <div class="kpi-grid3" id="kpi-grid2"></div>

  <!-- 検査実施状況 -->
  <div class="sec-head green">✅ 検査実施状況 — ID突合済み（全受診者）</div>
  <div class="bin-grid" id="bin-grid"></div>

  <!-- チャート -->
  <div class="sec-head">🎯 全体リスク像</div>
  <div class="chart-grid-2">
    <div class="chart-card">
      <div class="chart-title">指標別リスク該当率（レーダー）</div>
      <canvas id="radarChart" height="280"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">指標別リスク該当率（横棒・降順）</div>
      <canvas id="barChart" height="280"></canvas>
    </div>
  </div>
  <div class="chart-grid-2">
    <div class="chart-card">
      <div class="chart-title">年代別 歩行速度低下リスク率</div>
      <canvas id="ageChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">フレイルリスク重複数の分布（9指標合計）</div>
      <canvas id="riskDistChart" height="220"></canvas>
    </div>
  </div>

  <!-- 高リスクリスト -->
  <div class="sec-head red">🚨 高リスク個人リスト（フォローアップ優先度順）</div>
  <div class="alert-box">
    <span class="alert-n" id="hi-n">-</span>
    <span class="alert-sub" id="hi-sub"></span>
    <div class="alert-tip">🔔 保健師による優先的なフォローアップが必要です</div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>ID</th><th>性別</th><th>年齢</th><th>重複数</th>
          <th>歩行↓</th><th>筋力↓</th><th>サルコ</th><th>骨密度↓</th><th>MCI</th><th>嚥下↓</th>
          <th>バランス↓</th><th>口腔FRL</th><th>J-CHS</th>
          <th>歩行速度<br>(m/s)</th><th>STS<br>(秒)</th><th>MoCA</th><th>SMI</th><th>T-score</th><th>EAT-10</th>
          <th>バランス<br>得点</th><th>口腔<br>総合点</th><th>J-CHS<br>スコア</th>
        </tr>
      </thead>
      <tbody id="risk-tbody"></tbody>
    </table>
  </div>
</div>
</div>

<script>
const D = {DATA_JS};
let filtered = D.records.slice();

function applyFilter() {{
  const sexVals = [...document.querySelectorAll('#sidebar input[type=checkbox][value="男性"],#sidebar input[type=checkbox][value="女性"]')]
    .filter(e=>e.checked).map(e=>e.value);
  const ageVals = [...document.querySelectorAll('#sidebar input[type=checkbox]')]
    .filter(e=>e.checked && !['男性','女性'].includes(e.value)).map(e=>e.value);
  filtered = D.records.filter(r=>
    (sexVals.includes(r.sx)) && (ageVals.length===0 || ageVals.includes(r.ag))
  );
  renderAll();
}}

function calcKPI(records, key, baseKey) {{
  const valid = records.filter(r=>r[baseKey]!==null && r[baseKey]!==undefined);
  const risk  = valid.filter(r=>r[key]===1);
  const pct   = valid.length>0 ? (risk.length/valid.length*100).toFixed(1) : '0.0';
  return {{risk:risk.length, valid:valid.length, pct:parseFloat(pct)}};
}}

function calcBIN(records, key) {{
  const n = records.filter(r=>r[key]===1).length;
  return {{n, pct:(n/records.length*100).toFixed(1)}};
}}

const KPI_CFG = [
  {{key:'fw',  base:'w1',  label:'歩行速度低下',      icon:'🚶', color:'#DC2626', basis:'AWGS2019: 歩行速度 < 1.0 m/s'}},
  {{key:'fs',  base:'sts', label:'下肢筋力低下',      icon:'🦵', color:'#EA580C', basis:'SPPB準拠: 5回STS ≥ 12秒'}},
  {{key:'fa',  base:'smi', label:'サルコペニア疑い',  icon:'💪', color:'#D97706', basis:'AWGS2019: SMI < 7.0(男)/5.7(女)'}},
  {{key:'fb',  base:'ts',  label:'骨密度低下',        icon:'🦴', color:'#CA8A04', basis:'WHO基準: Tスコア ≤ −1.0 SD'}},
  {{key:'fm',  base:'moca',label:'MCI疑い',           icon:'🧠', color:'#7C3AED', basis:'Nasreddine 2005: MoCA ≤ 25点'}},
  {{key:'fe',  base:'eat', label:'嚥下機能低下リスク',icon:'🍽', color:'#0284C7', basis:'Belafsky 2008: EAT-10 ≥ 3点'}},
];

const KPI_CFG2 = [
  {{key:'fbal',  base:'bal',  label:'バランス能力低下',  icon:'⚖️', color:'#0891B2', basis:'SPPB: バランス得点 < 4点（満点4）'}},
  {{key:'foral', base:'oral', label:'オーラルフレイル', icon:'👄', color:'#059669', basis:'口腔フレイル総合点 ≥ 1点'}},
  {{key:'ffrail',base:'jchs', label:'J-CHSフレイル',    icon:'🏃', color:'#9333EA', basis:'J-CHS ≥ 3項目（低活動・体重減少・疲労・歩行・握力）'}},
];

const BIN_CFG = [
  {{key:'bf', label:'評価用紙', color:'#475569', desc:'問診・質問紙',          riskKey:null}},
  {{key:'bs', label:'SPPB',    color:'#EA580C', desc:'短身体機能バッテリー',   riskKey:'fw', riskLabel:'歩行速度低下'}},
  {{key:'be', label:'EAT-10',  color:'#0284C7', desc:'嚥下スクリーニング',    riskKey:'fe', riskLabel:'嚥下リスク≥3点'}},
  {{key:'bm', label:'MoCA-J',  color:'#7C3AED', desc:'認知機能スクリーニング',riskKey:'fm', riskLabel:'MCI疑い≤25点'}},
  {{key:'bi', label:'InBody',  color:'#D97706', desc:'体組成・SMI測定',       riskKey:'fa', riskLabel:'サルコペニア疑い'}},
  {{key:'bb', label:'骨密度',  color:'#CA8A04', desc:'超音波骨密度',          riskKey:'fb', riskLabel:'骨密度低下'}},
];

function hexToRgba(hex, alpha) {{
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
}}

let radarChart, barChart, ageChart, riskDistChart;

function kpiCardHtml(cfg, s) {{
  const bar = Math.min(s.pct,100).toFixed(1);
  return `<div class="kpi-card" style="--ac:${{cfg.color}}">
    <div class="kpi-icon">${{cfg.icon}}</div>
    <div class="kpi-name">${{cfg.label}}</div>
    <div><span class="kpi-pct">${{s.pct.toFixed(1)}}</span><span class="kpi-unit">%</span></div>
    <div class="kpi-detail">リスク <b>${{s.risk}}名</b> ／ 正常 ${{s.valid-s.risk}}名</div>
    <div class="kpi-detail" style="color:#64748B">測定 N=${{s.valid}}名</div>
    <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width:${{bar}}%"></div></div>
    <div class="kpi-basis">📐 ${{cfg.basis}}</div>
  </div>`;
}}

function renderKPI() {{
  const grid = document.getElementById('kpi-grid');
  grid.innerHTML = KPI_CFG.map(cfg=>kpiCardHtml(cfg, calcKPI(filtered,cfg.key,cfg.base))).join('');
}}

function renderKPI2() {{
  const grid = document.getElementById('kpi-grid2');
  grid.innerHTML = KPI_CFG2.map(cfg=>kpiCardHtml(cfg, calcKPI(filtered,cfg.key,cfg.base))).join('');
}}

function renderBIN() {{
  const grid = document.getElementById('bin-grid');
  grid.innerHTML = '';
  const icons = {{bf:'📋',bs:'🚶',be:'🍽',bm:'🧠',bi:'💪',bb:'🦴'}};
  BIN_CFG.forEach(cfg=>{{
    const s = calcBIN(filtered, cfg.key);
    let riskHtml = '';
    if(cfg.riskKey) {{
      const impl = filtered.filter(r=>r[cfg.key]===1);
      const rN   = impl.filter(r=>r[cfg.riskKey]===1).length;
      const rPct = impl.length>0 ? (rN/impl.length*100).toFixed(1) : '0.0';
      riskHtml = `<div class="risk-sub" style="--ac:${{cfg.color}};--ac-bg:${{hexToRgba(cfg.color,0.09)}}">
        <div class="risk-sub-lbl">${{cfg.riskLabel}}</div>
        <div class="risk-sub-pct">${{rPct}}<span style="font-size:11px">%</span>
          <span style="font-size:10px;color:#475569;margin-left:3px">${{rN}}/${{impl.length}}名</span>
        </div></div>`;
    }}
    const bar = Math.min(parseFloat(s.pct),100).toFixed(1);
    grid.innerHTML += `<div class="bin-card" style="--ac:${{cfg.color}}">
      <div class="kpi-icon" style="font-size:18px">${{icons[cfg.key]||'📊'}}</div>
      <div class="kpi-name">${{cfg.label}}</div>
      <div class="bin-n">${{s.n}}</div>
      <div class="bin-pct">実施率 <b>${{s.pct}}%</b>（${{filtered.length}}名中）</div>
      <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width:${{bar}}%"></div></div>
      <div class="bin-lbl">📎 ${{cfg.desc}}</div>
      ${{riskHtml}}</div>`;
  }});
}}

function renderRadar() {{
  const ctx = document.getElementById('radarChart').getContext('2d');
  if(radarChart) radarChart.destroy();
  const allCfg = [...KPI_CFG, ...KPI_CFG2];
  const labels = allCfg.map(c=>c.icon+' '+c.label.replace('機能低下リスク','↓'));
  const vals   = allCfg.map(c=>{{
    const s=calcKPI(filtered,c.key,c.base);
    return parseFloat(s.pct.toFixed(1));
  }});
  radarChart = new Chart(ctx,{{
    type:'radar',
    data:{{labels, datasets:[
      {{label:'背景',data:Array(9).fill(100),fill:true,backgroundColor:'rgba(226,232,240,0.35)',borderColor:'#CBD5E1',borderWidth:1,pointRadius:0}},
      {{label:'リスク該当率',data:vals,fill:true,backgroundColor:'rgba(220,38,38,0.12)',borderColor:'#DC2626',borderWidth:2.5,pointBackgroundColor:'#DC2626',pointRadius:4,pointHoverRadius:6}}
    ]}},
    options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
      scales:{{r:{{min:0,max:100,ticks:{{stepSize:25,callback:v=>v+'%',font:{{size:9}}}},
        grid:{{color:'#E2E8F0'}},angleLines:{{color:'#CBD5E1'}},pointLabels:{{font:{{size:9}},color:'#1E3A5F'}}}}}}}}
  }});
}}

function renderBar() {{
  const ctx = document.getElementById('barChart').getContext('2d');
  if(barChart) barChart.destroy();
  const allCfg = [...KPI_CFG,...KPI_CFG2];
  const sorted = allCfg.map(c=>{{
    const s=calcKPI(filtered,c.key,c.base);
    return {{...c,pct:parseFloat(s.pct.toFixed(1)),n:s.risk,v:s.valid}};
  }}).sort((a,b)=>b.pct-a.pct);
  barChart = new Chart(ctx,{{
    type:'bar',
    data:{{
      labels:sorted.map(c=>c.icon+' '+c.label),
      datasets:[
        {{data:Array(sorted.length).fill(100),backgroundColor:'#F1F5F9',borderWidth:0,label:''}},
        {{data:sorted.map(c=>c.pct),backgroundColor:sorted.map(c=>c.color),borderWidth:0,label:'リスク該当率'}}
      ]
    }},
    options:{{
      indexAxis:'y',responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},
        tooltip:{{callbacks:{{label:ctx=>` ${{ctx.parsed.x.toFixed(1)}}%　${{sorted[ctx.dataIndex].n}}/${{sorted[ctx.dataIndex].v}}名`}}}}
      }},
      scales:{{
        x:{{stacked:false,max:120,ticks:{{callback:v=>v+'%',font:{{size:10}}}},grid:{{color:'#E2E8F0'}}}},
        y:{{ticks:{{font:{{size:10}},color:'#1E3A5F'}},grid:{{display:false}}}}
      }}
    }}
  }});
}}

function renderAge() {{
  const ctx = document.getElementById('ageChart').getContext('2d');
  if(ageChart) ageChart.destroy();
  const AGE_LABS = ['65歳未満','65-69歳','70-74歳','75-79歳','80歳以上'];
  const agePct = AGE_LABS.map(ag=>{{
    const sub   = filtered.filter(r=>r.ag===ag);
    const valid = sub.filter(r=>r.w1!==null);
    const risk  = valid.filter(r=>r.fw===1);
    return valid.length>0 ? parseFloat((risk.length/valid.length*100).toFixed(1)) : 0;
  }});
  const ageN = AGE_LABS.map(ag=>filtered.filter(r=>r.ag===ag).length);
  ageChart = new Chart(ctx,{{
    type:'bar',
    data:{{labels:AGE_LABS,datasets:[
      {{label:'歩行速度低下',data:agePct,backgroundColor:'rgba(234,88,12,0.78)',borderWidth:0,borderRadius:5,borderSkipped:false}},
      {{label:'正常',data:agePct.map(p=>100-p),backgroundColor:'rgba(203,213,225,0.45)',borderWidth:0,borderRadius:5,borderSkipped:false}}
    ]}},
    options:{{
      responsive:true,maintainAspectRatio:false,
      plugins:{{
        legend:{{position:'bottom',labels:{{font:{{size:10}}}}}},
        tooltip:{{callbacks:{{
          label:ctx=>ctx.datasetIndex===0?` 歩行速度低下 ${{ctx.parsed.y.toFixed(1)}}%`:` 正常 ${{ctx.parsed.y.toFixed(1)}}%`,
          afterBody:(items)=>[`N=${{ageN[items[0].dataIndex]}}名`]
        }}}}
      }},
      scales:{{
        x:{{stacked:true,ticks:{{font:{{size:10}},color:'#1E3A5F'}},grid:{{display:false}}}},
        y:{{stacked:true,max:100,ticks:{{callback:v=>v+'%',font:{{size:10}}}},grid:{{color:'#E2E8F0'}}}}
      }}
    }}
  }});
}}

function renderRiskDist() {{
  const ctx = document.getElementById('riskDistChart').getContext('2d');
  if(riskDistChart) riskDistChart.destroy();
  const counts = Array.from({{length:10}},(_,k)=>filtered.filter(r=>r.risks===k).length);
  const colors = ['#16A34A','#65A30D','#B45309','#EA580C','#DC2626','#B91C1C','#9B1C1C','#7F1D1D','#6B1B1B','#450A0A'];
  riskDistChart = new Chart(ctx,{{
    type:'bar',
    data:{{
      labels:counts.map((_,k)=>`${{k}}項目`),
      datasets:[{{data:counts,backgroundColor:colors,borderWidth:0,borderRadius:6,borderSkipped:false,label:'人数'}}]
    }},
    options:{{
      responsive:true,maintainAspectRatio:false,
      plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>`${{ctx.parsed.y}}名 (${{(ctx.parsed.y/Math.max(filtered.length,1)*100).toFixed(1)}}%)`}}}}
      }},
      scales:{{
        x:{{ticks:{{font:{{size:10}},color:'#1E3A5F'}},grid:{{display:false}}}},
        y:{{ticks:{{font:{{size:10}}}},grid:{{color:'#E2E8F0'}},title:{{display:true,text:'人数（名）',font:{{size:10}}}}}}
      }}
    }}
  }});
}}

function renderHighRisk() {{
  const minR = parseInt(document.getElementById('min-risk').value);
  const hi   = filtered.filter(r=>r.risks>=minR).sort((a,b)=>b.risks-a.risks);
  document.getElementById('hi-n').textContent = hi.length;
  document.getElementById('hi-sub').textContent =
    `（対象${{filtered.length}}名中 ${{(hi.length/Math.max(filtered.length,1)*100).toFixed(1)}}%）に${{minR}}項目以上のリスクが重複`;
  const badges = n=>n===0?'<span class="risk-badge-0">0</span>':n<=1?`<span class="risk-badge-1">${{n}}</span>`:n<=2?`<span class="risk-badge-2">${{n}}</span>`:`<span class="risk-badge-3">${{n}}</span>`;
  const flag   = (v,yes='🔴',no='✅')=>v===1?`<td class="risk-flag-yes">${{yes}}</td>`:`<td class="risk-flag-no">${{no}}</td>`;
  const fmt    = (v,d=2)=>v===null||v===undefined?'—':v.toFixed(d);
  const fmti   = v=>v===null||v===undefined?'—':v;
  document.getElementById('risk-tbody').innerHTML = hi.map(r=>`
    <tr>
      <td>${{r.id}}</td>
      <td>${{r.sx||'—'}}</td>
      <td>${{r.age||'—'}}</td>
      <td>${{badges(r.risks)}}</td>
      ${{flag(r.fw)}}${{flag(r.fs)}}${{flag(r.fa)}}${{flag(r.fb)}}${{flag(r.fm)}}${{flag(r.fe)}}
      ${{flag(r.fbal)}}${{flag(r.foral)}}${{flag(r.ffrail)}}
      <td>${{fmt(r.w1,3)}}</td><td>${{fmt(r.sts,1)}}</td>
      <td>${{fmti(r.moca)}}</td><td>${{fmt(r.smi,2)}}</td><td>${{fmt(r.ts,2)}}</td><td>${{fmti(r.eat)}}</td>
      <td>${{fmti(r.bal)}}</td><td>${{fmti(r.oral)}}</td><td>${{fmt(r.jchs,1)}}</td>
    </tr>`).join('');
}}

function renderSidebarStat() {{
  const N  = filtered.length;
  const nm = filtered.filter(r=>r.sx==='男性').length;
  const nf = filtered.filter(r=>r.sx==='女性').length;
  const r4 = filtered.filter(r=>r.risks>=4).length;
  document.getElementById('sb-n').textContent = N;
  document.getElementById('sb-m').textContent = nm;
  document.getElementById('sb-f').textContent = nf;
  document.getElementById('sb-r4').textContent = r4;
  document.getElementById('hdr-n').textContent = N;
  document.getElementById('hdr-sub').textContent = `男性${{nm}}名 ／ 女性${{nf}}名`;
  const sexChk = [...document.querySelectorAll('#sidebar input[type=checkbox][value="男性"],#sidebar input[type=checkbox][value="女性"]')]
    .filter(e=>e.checked).map(e=>e.value);
  const ageChk = [...document.querySelectorAll('#sidebar input[type=checkbox]')]
    .filter(e=>e.checked && !['男性','女性'].includes(e.value)).map(e=>e.value);
  const sexStr = sexChk.length===2?'全性別':sexChk.join('・')||'なし';
  const ageStr = ageChk.length===5?'全年齢':ageChk.length===0?'なし':ageChk.join('・');
  document.getElementById('filter-info').textContent =
    `フィルター適用中: ${{N}}名 ／ ${{ageStr}} ／ ${{sexStr}}`;
}}

function renderAll() {{
  renderSidebarStat();
  renderKPI();
  renderKPI2();
  renderBIN();
  renderRadar();
  renderBar();
  renderAge();
  renderRiskDist();
  renderHighRisk();
}}

renderAll();
</script>
</body>
</html>"""

out_path = os.path.join(HERE, 'frail_dashboard_2025.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

size_kb = os.path.getsize(out_path) // 1024
print(f"生成完了: {out_path}")
print(f"ファイルサイズ: {size_kb} KB")
