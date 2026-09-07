# -*- coding: utf-8 -*-
"""店舗目標タブを「月ごとブロック」レイアウトに作り替える"""
import sys, argparse
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path.home() / "projects/pilates-rag-agent/src"))
from common import get_gspread_client

SSID = "1K0_PP4mGQBHzzKYOo2E8bulcwSJJVShS8JK875bdoZA"
TAB = "店舗目標"
OLD = "店舗目標(旧)"

# 店舗 → (目標列index 0-based, 参照元タブの列)
STORES = [
    ("川越",     1,  {"uriage": "B", "keiyaku": "D", "kaiyaku_r": "T", "kaiyaku_n": "H", "kaiin": "N"}),
    ("大宮",     4,  {"uriage": "C", "keiyaku": "G", "kaiyaku_r": "U", "kaiyaku_n": "I", "kaiin": "O"}),
    ("高崎",     7,  {"uriage": "E", "keiyaku": "M", "kaiyaku_r": "W", "kaiyaku_n": "K", "kaiin": "Q"}),
    ("神戸元町", 10, {"uriage": "D", "keiyaku": "J", "kaiyaku_r": "V", "kaiyaku_n": "J", "kaiin": "P"}),
    ("西宮北口", 13, {"uriage": "F", "keiyaku": "P", "kaiyaku_r": "X", "kaiyaku_n": "L", "kaiin": "R"}),
    ("所沢",     16, {"uriage": "G", "keiyaku": "S", "kaiyaku_r": "Y", "kaiyaku_n": "M", "kaiin": "S"}),
    # 浦和は新店。売上/契約率/解約率タブに列ができたら参照を書いて自動反映に切り替える
    ("浦和",     19, {}),
]
NCOL = 22  # A..V
HEAD = 3
BLOCK = 14
MONTHS = [(2026, 9), (2026, 10), (2026, 11), (2026, 12), (2027, 1)]

# 項目定義: (ラベル, 種別, 数値書式, 低いほど良いか)
ITEMS = [
    ("売上（万円）",         "uriage",    '#,##0"万"', False),
    ("消化売上（万円）",     None,        '#,##0"万"', False),
    ("契約率",               "keiyaku",   "0.0%",      False),
    ("解約率",               "kaiyaku_r", "0.0%",      True),
    ("解約数",               "kaiyaku_n", "#,##0",     True),
    ("会員数（月末）",       "kaiin",     "#,##0",     False),
    ("口コミ獲得数",         None,        "#,##0",     False),
    ("中間カウンセリング",   None,        "#,##0",     False),
    ("その他（自由記入）",     None,      None,        False),
]

KPI_HEAD = "KPI（数字の目標）"
KPI_HEAD_MEMO = "※各店の「目標」を月初に入力してください。「結果」は薄い青のセルに自動で入ります"
KDI_HEAD = "KDI（行動の目標）"
KDI_HEAD_MEMO = "※KPIを達成するために、誰が・いつ・どのくらいの頻度でやるのかを書きます"
KDI_LABEL = "今月やる行動\n※誰が・いつ・どのくらいの頻度で"

# A列ラベルの正規化（改行前まで）と旧ラベルの読み替え。手入力の退避キーに使う
LABEL_ALIAS = {
    "KDI（今月やる行動）": "今月やる行動",
    "その他（項目名を記入）": "その他（自由記入）",
}


def norm_label(x):
    t = str(x).split("\n")[0].strip()
    return LABEL_ALIAS.get(t, t)
KDI_NOTE = (
    "【KDIの書き方】\n"
    "「誰が」「いつ」「どのくらいの頻度で」やるのかまで書いてください。\n"
    "※あいまいな行動目標（例：口コミを増やす）はNGです。\n\n"
    "例）AKIが、毎週月曜の朝礼後に、既存会員へ中間カウンセリングの声かけを5件ずつ実施\n"
    "例）店長が、毎日の最終レッスン後に、その日の新規のお客様へGoogle口コミを1件依頼\n"
    "例）スタッフ全員が、毎月1日と15日に、年払い案内のLINEを担当会員へ配信"
)
FURI_NOTE = (
    "【振り返りの書き方】\n"
    "①数字の結果（達成／未達とその理由）\n"
    "②KDI（今月やる行動）を決めたとおりに実行できたか\n"
    "③来月に変えること\n"
    "の3つを書いてください。"
)

C_HEAD_BG   = {"red": 0.184, "green": 0.235, "blue": 0.286}   # 濃紺グレー
C_HEAD_FG   = {"red": 1, "green": 1, "blue": 1}
C_MONTH_BG  = {"red": 0.949, "green": 0.925, "blue": 0.867}   # ベージュ
C_GROUP_BG  = {"red": 0.906, "green": 0.898, "blue": 0.882}   # KPI/KDI見出しの帯
C_GROUP_FG  = {"red": 0.45,  "green": 0.44,  "blue": 0.42}
C_MONTH_FG  = {"red": 0.361, "green": 0.286, "blue": 0.129}
C_ITEM_BG   = {"red": 0.969, "green": 0.969, "blue": 0.961}
C_AUTO_BG   = {"red": 0.918, "green": 0.945, "blue": 0.973}   # 薄青=自動
C_MEMO_BG   = {"red": 0.992, "green": 0.988, "blue": 0.976}
C_BORDER    = {"red": 0.82, "green": 0.82, "blue": 0.80}
C_BLOCKLINE = {"red": 0.55, "green": 0.55, "blue": 0.53}


def cl(i):  # 0-based -> A1 column letter
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def month_serial(y, m):
    """Google スプレッドシートの日付シリアル値（基準 1899/12/30）"""
    return (date(y, m, 1) - date(1899, 12, 30)).days


def snapshot_manual(ws):
    """作り直しで消えないよう、既存レイアウトの手入力を吸い出す

    戻り値: ({(月シリアル, 正規化ラベル, 店舗名, 目標/結果): 値}, {月シリアル: 自由記入行の元ラベル})
    レイアウトが違う(初回)場合は空を返す。
    """
    ncol = min(ws.col_count, 40)
    try:
        v = ws.get(f"A1:{cl(ncol - 1)}300", value_render_option="FORMULA")
    except Exception:
        return {}, {}
    v = [(r + [""] * ncol)[:ncol] for r in v]
    if len(v) < 4:
        return {}, {}
    cols = [(str(v[1][j]).strip(), j) for j in range(1, ncol) if str(v[1][j]).strip()]
    if not cols:
        return {}, {}
    known = {norm_label(l) for l, _, _, _ in ITEMS} | {"今月やる行動", "振り返り"}
    out, free_labels, cur = {}, {}, None
    for i in range(3, len(v)):
        a = str(v[i][0]).strip()
        try:                      # 月見出し行(日付シリアル)ならブロックの起点
            cur = int(float(a))
            continue
        except ValueError:
            pass
        if cur is None or not a:
            continue
        lab = norm_label(a)
        if lab in (KPI_HEAD, KDI_HEAD):
            continue              # グループ見出し行。B列のメモを目標欄と誤認しないため
        if lab not in known:      # 自由記入行のラベルを書き換えている場合
            free_labels[cur] = a
            lab = "その他（自由記入）"
        for name, g in cols:
            for off, kind in ((0, "目標"), (1, "結果")):
                if g + off >= ncol:
                    continue
                c = v[i][g + off]
                if str(c).strip() and not str(c).startswith("="):
                    out[(cur, lab, name, kind)] = c
    return out, free_labels


def f_uriage(col, mr):
    return ('=IFERROR(LET(r,MATCH($A{m},\'売上(2026年度)\'!$A:$A,0),'
            'v,INDEX(\'売上(2026年度)\'!${c}:${c},r),'
            'IF(N(v)=0,"",v/10000)),"")').format(m=mr, c=col)


def f_keiyaku(col, mr):
    return ('=IFERROR(LET(r,IFERROR(MATCH($A{m},契約率!$A:$A,0),'
            'MATCH(TEXT($A{m},"yyyy年m月"),契約率!$A:$A,0)),'
            'v,INDEX(契約率!${c}:${c},r),IF(v="","",v)),"")').format(m=mr, c=col)


def f_kaiyaku(col, mr):
    return ('=IFERROR(LET(r,MATCH($A{m},解約率!$A:$A,0),'
            'v,INDEX(解約率!${c}:${c},r),IF(v="","",v)),"")').format(m=mr, c=col)


def f_judge(gc_, rc_, row, lower):
    op = "<=" if lower else ">="
    return ('=IF(OR({g}{r}="",{v}{r}=""),"",'
            'IF({v}{r}{o}{g}{r},"達成","未達"))').format(g=gc_, v=rc_, r=row, o=op)


# 2026年9月の既存目標（旧タブから移設）
SEP_GOALS = {
    "川越":     {"売上（万円）": 500, "契約率": "65%", "解約率": "3.0%", "解約数": 5, "会員数（月末）": 200},
    "神戸元町": {"売上（万円）": 650, "消化売上（万円）": 600, "契約率": "60%", "解約数": 5, "口コミ獲得数": 30},
    "西宮北口": {"売上（万円）": 480, "消化売上（万円）": 350, "契約率": "55%", "会員数（月末）": 170,
                 "解約数": 4, "口コミ獲得数": 30},
}
SEP_KDI = {
    "川越": "9月の予想新規予約数→20件と予想。65%入会となると13名の入会が必要。\n"
            "サブスク引き落とし予定額（9/3現）：369万",
    "西宮北口": "契約率55％（目標65％以上）／年払い獲得",
}


def build():
    gc = get_gspread_client()
    sh = gc.open_by_key(SSID)
    ws = sh.worksheet(TAB)
    sid = ws.id

    # 0) 既存の手入力を退避（作り直しで消さないため）
    snap, snap_labels = snapshot_manual(ws)
    print(f"  💾 既存の手入力 {len(snap)}件を退避")

    # 1) 旧タブへ退避
    titles = [w.title for w in sh.worksheets()]
    if OLD in titles:
        print(f"  ⏭ 「{OLD}」は既に存在 → 退避スキップ")
    else:
        dup = sh.duplicate_sheet(source_sheet_id=sid, new_sheet_name=OLD,
                                 insert_sheet_index=len(titles))
        print(f"  ✅ 「{OLD}」に退避（gid={dup.id}）")

    need_rows = HEAD + BLOCK * len(MONTHS)

    # 2) 事前バッチ: 既存の条件付き書式削除 → マージ解除 → 全消去 → 列追加 → 固定行
    pre = []
    meta = sh.fetch_sheet_metadata()
    cf_n = 0
    for s_ in meta.get("sheets", []):
        if s_["properties"]["sheetId"] == sid:
            cf_n = len(s_.get("conditionalFormats", []))
    for i in range(cf_n - 1, -1, -1):
        pre.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
    pre.append({"unmergeCells": {"range": {"sheetId": sid}}})
    pre.append({"updateCells": {"range": {"sheetId": sid},
                                "fields": "userEnteredValue,userEnteredFormat,note"}})
    if ws.col_count < NCOL:
        pre.append({"appendDimension": {"sheetId": sid, "dimension": "COLUMNS",
                                        "length": NCOL - ws.col_count}})
    pre.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0,
                  "endIndex": ws.row_count},
        "properties": {"pixelSize": 22}, "fields": "pixelSize"}})
    pre.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": HEAD,
                                                          "frozenColumnCount": 1}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})
    sh.batch_update({"requests": pre})
    print(f"  ✅ 初期化（既存の条件付き書式 {cf_n}件を削除・マージ解除・全消去・列を{NCOL}列に）")

    reqs = []

    # 3) 列幅
    def dim(kind, s, e, px):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": kind, "startIndex": s, "endIndex": e},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    dim("COLUMNS", 0, 1, 140)
    for _, gcol, _ in STORES:
        dim("COLUMNS", gcol, gcol + 2, 65)
        dim("COLUMNS", gcol + 2, gcol + 3, 44)
    dim("ROWS", 0, 1, 26)
    dim("ROWS", 1, 3, 22)

    # 4) 値・数式
    values = [["" for _ in range(NCOL)] for _ in range(need_rows)]
    pos = {}   # (月シリアル, ブロック内行番号, 店舗名, 目標/結果) -> (row0, col0)
    lab_pos = {}

    values[0][0] = "店舗目標"
    values[0][1] = ("KPI＝数字の目標／KDI＝そのためにやる行動　｜　"
                    "■薄い青のセル＝自動反映（さわらないでね）　□白いセル＝手で入力　"
                    "判定は目標と結果が両方埋まったら自動で出ます　"
                    "★KDIは「誰が・いつ・どのくらいの頻度で」まで書いてね")
    values[1][0] = "項目"
    for name, gcol, _ in STORES:
        values[1][gcol] = name
        values[2][gcol] = "目標"
        values[2][gcol + 1] = "結果"
        values[2][gcol + 2] = "判定"

    for bi, (y, m) in enumerate(MONTHS):
        mr0 = HEAD + bi * BLOCK          # 0-based 月見出し行
        mr = mr0 + 1                     # 1-based
        values[mr0][0] = f"{y}/{m}/1"
        ser = month_serial(y, m)
        values[mr0 + 1][0] = KPI_HEAD
        values[mr0 + 1][1] = KPI_HEAD_MEMO
        for k, (label, kind, numfmt, lower) in enumerate(ITEMS):
            r0 = mr0 + 2 + k
            r = r0 + 1
            values[r0][0] = label
            lab_pos[ser] = r0 if label == "その他（自由記入）" else lab_pos.get(ser)
            for name, gcol, ref in STORES:
                pos[(ser, norm_label(label), name, "目標")] = (r0, gcol)
                pos[(ser, norm_label(label), name, "結果")] = (r0, gcol + 1)
                g, v, j = cl(gcol), cl(gcol + 1), cl(gcol + 2)
                if kind and ref:
                    if kind == "uriage":
                        values[r0][gcol + 1] = f_uriage(ref["uriage"], mr)
                    elif kind == "keiyaku":
                        values[r0][gcol + 1] = f_keiyaku(ref["keiyaku"], mr)
                    else:
                        values[r0][gcol + 1] = f_kaiyaku(ref[kind], mr)
                if label != "その他（自由記入）":
                    values[r0][gcol + 2] = f_judge(g, v, r, lower)
                # 9月の既存目標を転記
                if (not snap and (y, m) == (2026, 9)
                        and name in SEP_GOALS and label in SEP_GOALS[name]):
                    values[r0][gcol] = SEP_GOALS[name][label]
        values[mr0 + 11][0] = KDI_HEAD
        values[mr0 + 11][1] = KDI_HEAD_MEMO
        values[mr0 + 12][0] = KDI_LABEL
        values[mr0 + 13][0] = "振り返り"
        for name, gcol, _ in STORES:
            pos[(ser, "今月やる行動", name, "目標")] = (mr0 + 12, gcol)
            pos[(ser, "振り返り", name, "目標")] = (mr0 + 13, gcol)
        if not snap and (y, m) == (2026, 9):
            for name, gcol, _ in STORES:
                if name in SEP_KDI:
                    values[mr0 + 12][gcol] = SEP_KDI[name]

    # 退避した手入力を書き戻す（「その他」行はA列のラベルも復元）
    back = 0
    for key, val in snap.items():
        if key in pos:
            r0, c0 = pos[key]
            values[r0][c0] = val
            back += 1
    for ser_, lab in snap_labels.items():
        if lab_pos.get(ser_) is not None:
            values[lab_pos[ser_]][0] = lab
    if snap:
        print(f"  ♻️ 手入力 {back}/{len(snap)}件を書き戻し")

    ws.batch_update([{"range": f"A1:{cl(NCOL - 1)}{need_rows}", "values": values}],
                    value_input_option="USER_ENTERED")
    print(f"  ✅ 値・数式を書き込み（{need_rows}行 × {NCOL}列）")

    # 5) 書式
    def rng(r0, r1, c0, c1):
        return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def cell(r0, r1, c0, c1, fmt, fields):
        reqs.append({"repeatCell": {"range": rng(r0, r1, c0, c1),
                                    "cell": {"userEnteredFormat": fmt}, "fields": fields}})

    # 全体ベース
    cell(0, need_rows, 0, NCOL,
         {"textFormat": {"fontSize": 10, "fontFamily": "Arial"},
          "verticalAlignment": "MIDDLE", "wrapStrategy": "CLIP"},
         "userEnteredFormat.textFormat,userEnteredFormat.verticalAlignment,"
         "userEnteredFormat.wrapStrategy")

    # 1行目 タイトル＋凡例
    reqs.append({"mergeCells": {"range": rng(0, 1, 1, NCOL), "mergeType": "MERGE_ALL"}})
    cell(0, 1, 0, 1, {"backgroundColor": C_HEAD_BG,
                      "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": C_HEAD_FG}},
         "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat")
    cell(0, 1, 1, NCOL, {"backgroundColor": C_MEMO_BG,
                         "textFormat": {"fontSize": 9, "foregroundColor":
                                        {"red": 0.35, "green": 0.35, "blue": 0.33}},
                         "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE"},
         "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat,"
         "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment")

    # 2-3行目 ヘッダ
    reqs.append({"mergeCells": {"range": rng(1, 3, 0, 1), "mergeType": "MERGE_ALL"}})
    for _, gcol, _ in STORES:
        reqs.append({"mergeCells": {"range": rng(1, 2, gcol, gcol + 3), "mergeType": "MERGE_ALL"}})
    cell(1, 3, 0, NCOL,
         {"backgroundColor": C_HEAD_BG, "horizontalAlignment": "CENTER",
          "textFormat": {"bold": True, "fontSize": 10, "foregroundColor": C_HEAD_FG}},
         "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,"
         "userEnteredFormat.textFormat")

    for bi, _ in enumerate(MONTHS):
        mr0 = HEAD + bi * BLOCK
        # 月見出し行
        reqs.append({"mergeCells": {"range": rng(mr0, mr0 + 1, 1, NCOL), "mergeType": "MERGE_ALL"}})
        cell(mr0, mr0 + 1, 0, NCOL,
             {"backgroundColor": C_MONTH_BG, "horizontalAlignment": "LEFT",
              "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": C_MONTH_FG},
              "numberFormat": {"type": "DATE", "pattern": "yyyy年m月"}},
             "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,"
             "userEnteredFormat.textFormat,userEnteredFormat.numberFormat")
        dim("ROWS", mr0, mr0 + 1, 30)
        # KPI / KDI のグループ見出し行
        for hr in (mr0 + 1, mr0 + 11):
            reqs.append({"mergeCells": {"range": rng(hr, hr + 1, 1, NCOL),
                                        "mergeType": "MERGE_ALL"}})
            cell(hr, hr + 1, 0, 1,
                 {"backgroundColor": C_GROUP_BG, "horizontalAlignment": "LEFT",
                  "wrapStrategy": "CLIP",
                  "textFormat": {"bold": True, "fontSize": 10,
                                 "foregroundColor": C_HEAD_BG}},
                 "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,"
                 "userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat")
            cell(hr, hr + 1, 1, NCOL,
                 {"backgroundColor": C_GROUP_BG, "horizontalAlignment": "LEFT",
                  "wrapStrategy": "CLIP",
                  "textFormat": {"bold": False, "fontSize": 9,
                                 "foregroundColor": C_GROUP_FG}},
                 "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,"
                 "userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat")
            dim("ROWS", hr, hr + 1, 24)
        # 項目行 A列
        for a0, a1 in ((mr0 + 2, mr0 + 11), (mr0 + 12, mr0 + 14)):
            cell(a0, a1, 0, 1,
                 {"backgroundColor": C_ITEM_BG, "horizontalAlignment": "LEFT",
                  "textFormat": {"bold": False, "fontSize": 10}, "wrapStrategy": "WRAP"},
                 "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment,"
                 "userEnteredFormat.textFormat,userEnteredFormat.wrapStrategy")
        # データセル
        cell(mr0 + 2, mr0 + 11, 1, NCOL,
             {"backgroundColor": {"red": 1, "green": 1, "blue": 1},
              "horizontalAlignment": "CENTER"},
             "userEnteredFormat.backgroundColor,userEnteredFormat.horizontalAlignment")
        # 自動反映セル(結果列)を薄青に
        for k, (label, kind, numfmt, lower) in enumerate(ITEMS):
            r0 = mr0 + 2 + k
            for _, gcol, ref in STORES:
                if kind and ref:
                    cell(r0, r0 + 1, gcol + 1, gcol + 2, {"backgroundColor": C_AUTO_BG},
                         "userEnteredFormat.backgroundColor")
                if numfmt:
                    cell(r0, r0 + 1, gcol, gcol + 2,
                         {"numberFormat": {"type": "NUMBER" if "%" not in numfmt else "PERCENT",
                                           "pattern": numfmt}},
                         "userEnteredFormat.numberFormat")
        # 判定列
        for _, gcol, _ in STORES:
            cell(mr0 + 2, mr0 + 11, gcol + 2, gcol + 3,
                 {"textFormat": {"fontSize": 9}}, "userEnteredFormat.textFormat")
        # KDI・振り返り行
        for rr in (mr0 + 12, mr0 + 13):
            note = KDI_NOTE if rr == mr0 + 12 else FURI_NOTE
            for _, gcol, _ in STORES:
                reqs.append({"mergeCells": {"range": rng(rr, rr + 1, gcol, gcol + 3),
                                            "mergeType": "MERGE_ALL"}})
                reqs.append({"repeatCell": {"range": rng(rr, rr + 1, gcol, gcol + 1),
                                            "cell": {"note": note}, "fields": "note"}})
            cell(rr, rr + 1, 0, 1, {"textFormat": {"fontSize": 9}},
                 "userEnteredFormat.textFormat")
            cell(rr, rr + 1, 1, NCOL,
                 {"backgroundColor": C_MEMO_BG, "wrapStrategy": "WRAP",
                  "horizontalAlignment": "LEFT", "verticalAlignment": "TOP",
                  "textFormat": {"fontSize": 9}},
                 "userEnteredFormat.backgroundColor,userEnteredFormat.wrapStrategy,"
                 "userEnteredFormat.horizontalAlignment,userEnteredFormat.verticalAlignment,"
                 "userEnteredFormat.textFormat")
            dim("ROWS", rr, rr + 1, 84 if rr == mr0 + 12 else 74)

    # 罫線
    reqs.append({"updateBorders": {
        "range": rng(0, need_rows, 0, NCOL),
        "innerHorizontal": {"style": "SOLID", "width": 1, "color": C_BORDER},
        "innerVertical": {"style": "SOLID", "width": 1, "color": C_BORDER},
        "top": {"style": "SOLID", "width": 1, "color": C_BORDER},
        "bottom": {"style": "SOLID", "width": 1, "color": C_BORDER},
        "left": {"style": "SOLID", "width": 1, "color": C_BORDER},
        "right": {"style": "SOLID", "width": 1, "color": C_BORDER}}})
    for bi, _ in enumerate(MONTHS):
        mr0 = HEAD + bi * BLOCK
        reqs.append({"updateBorders": {
            "range": rng(mr0, mr0 + 1, 0, NCOL),
            "top": {"style": "SOLID_MEDIUM", "width": 2, "color": C_BLOCKLINE}}})
    # 店舗ブロックの縦仕切り
    for _, gcol, _ in STORES:
        reqs.append({"updateBorders": {
            "range": rng(1, need_rows, gcol, gcol + 3),
            "left": {"style": "SOLID_MEDIUM", "width": 2, "color": C_BLOCKLINE}}})

    # 条件付き書式（判定列）
    jcols = [gcol + 2 for _, gcol, _ in STORES]
    ranges = [rng(HEAD, need_rows, c, c + 1) for c in jcols]
    for i, (word, bg, fg) in enumerate([
            ("達成", {"red": 0.878, "green": 0.941, "blue": 0.867},
                     {"red": 0.145, "green": 0.396, "blue": 0.114}),
            ("未達", {"red": 0.984, "green": 0.882, "blue": 0.882},
                     {"red": 0.639, "green": 0.176, "blue": 0.176})]):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": ranges,
            "booleanRule": {
                "condition": {"type": "TEXT_EQ",
                              "values": [{"userEnteredValue": word}]},
                "format": {"backgroundColor": bg,
                           "textFormat": {"bold": True, "foregroundColor": fg}}}}}})

    sh.batch_update({"requests": reqs})
    print(f"  ✅ 書式を適用（リクエスト {len(reqs)}件）")
    print(f"\n🎀 完了！ https://docs.google.com/spreadsheets/d/{SSID}/edit#gid={sid}")


if __name__ == "__main__":
    build()
