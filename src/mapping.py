"""复核表字段 → 目标表「媒体回执」列位置 的映射。

依据用户给定的分工图:
- A-M(1-13)媒介手工填,AI 不碰;S-T 拉流暂缓;是否出票/接送机/住宿不填。
- AI 只填:出席人组(14-17)+ 去程(21-27 事实字段)+ 返程(30-36 事实字段)。
- 因表头有重复列名(职位/联系方式/交通类型各两次),**必须按列位置写,不能按列名**。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fields import LEG_FIELDS, LEGS  # noqa: E402

# 复核表扁平字段 → 目标表 1-based 列号(直接映射的)
DIRECT_COL = {
    "姓名": 14,        # 出席人
    "职位": 15,
    "电话": 16,        # 联系方式
    "身份证号": 17,    # 身份证号码
    "去程-方式": 21,   # 交通类型
    "去程-日期": 22,
    "去程-航班车次": 24,
    "去程-出发时间": 26,
    "去程-到达时间": 27,
    "返程-方式": 30,
    "返程-日期": 31,
    "返程-航班车次": 33,
    "返程-出发时间": 35,
    "返程-到达时间": 36,
}
# 出发地-抵达地(合并列)
CITY_COL = {"去程": 23, "返程": 32}
# 航站楼:去程填「到达航站楼」,返程填「出发航站楼」
TERMINAL_COL = {"去程": 25, "返程": 34}

NCOLS = 38  # 写到「是否送机」为止;其余留空

# AI 会写的列(供试算展示 / 校验锚点)
AI_COLS = sorted(set(DIRECT_COL.values()) | set(CITY_COL.values()) | set(TERMINAL_COL.values()))

# 锚点校验:核对目标表这些列的表头是否符合预期,防止模板变动写错列
HEADER_ANCHORS = {
    14: "出席人", 17: "身份证号码", 21: "交通类型", 23: "出发地-抵达地",
    24: "航班/车次", 30: "交通类型", 32: "出发地-抵达地",
}


def _pick_terminal(term, leg):
    """去程取到达侧、返程取出发侧;'首都T3-天河T3' 之类按 '-' 拆。"""
    term = (term or "").strip()
    if not term:
        return ""
    if "-" in term:
        a, b = term.split("-", 1)
        return (b if leg == "去程" else a).strip()
    return term


def build_sheet_row(rec):
    """把一条(已合并出行程的)出席人记录,拼成长度 NCOLS 的行值列表。"""
    row = [""] * NCOLS

    def put(idx, val):
        val = (val or "").strip()
        if val:
            row[idx - 1] = val

    for f, idx in DIRECT_COL.items():
        put(idx, rec.get(f, ""))
    for leg in LEGS:
        dep = (rec.get(f"{leg}-出发城市", "") or "").strip()
        arr = (rec.get(f"{leg}-到达城市", "") or "").strip()
        parts = [x for x in (dep, arr) if x]
        put(CITY_COL[leg], "-".join(parts) if parts else "")
        put(TERMINAL_COL[leg], _pick_terminal(rec.get(f"{leg}-航站楼", ""), leg))
    return row


def check_header(header):
    """核对目标表头锚点。返回不匹配列表 [(列号, 期望, 实际)];空则通过。"""
    bad = []
    for idx, expect in HEADER_ANCHORS.items():
        actual = (header[idx - 1] if idx - 1 < len(header) else "") or ""
        actual = str(actual).replace("\n", "").strip()
        if expect not in actual:
            bad.append((idx, expect, actual))
    return bad


def has_travel(rec):
    return any((rec.get(f"{leg}-{f}", "") or "").strip() for leg in LEGS for f in LEG_FIELDS)


def has_identity(rec):
    return any((rec.get(k, "") or "").strip() for k in ("身份证号", "电话", "媒体名称"))


def merge_records(rows):
    """把复核表读回的行,合并成 出席人记录列表 + 未认领行程列表。

    - 有身份信息(身份证/电话/媒体名称)→ 出席人;
    - 只有行程 → 待认领,按「姓名」并入同名出席人;并不上就单列。
    """
    persons, trips = [], []
    for r in rows:
        if has_identity(r):
            persons.append(dict(r))
        elif has_travel(r):
            trips.append(dict(r))

    by_name = {}
    for p in persons:
        nm = (p.get("姓名", "") or "").strip()
        if nm:
            by_name.setdefault(nm, p)

    unassigned = []
    for t in trips:
        nm = (t.get("姓名", "") or "").strip()
        tgt = by_name.get(nm)
        if tgt:
            for leg in LEGS:
                for f in LEG_FIELDS:
                    k = f"{leg}-{f}"
                    if (t.get(k, "") or "").strip() and not (tgt.get(k, "") or "").strip():
                        tgt[k] = t[k]
        else:
            unassigned.append(t)
    return persons, unassigned
