"""从一个单元(一个人或一坨群聊/行程截图)提取:多人媒介资料 + 行程。

设计要点(已与用户确认):
- people: 群聊里可能多人,逐人成对象;媒体名称只认"媒体名称:"标注,不认聊天昵称抬头。
- itineraries: 行程截图通常无出行人姓名,不硬猜归属;
  单人单元 → 行程直接挂该人;多人/裸行程 → 进「待认领行程」交人工。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fields import LEG_FIELDS, LEGS, MEDIA_FIELDS  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
TEXT_EXTS = {".txt", ".md"}

SYSTEM_PROMPT = "你是媒介活动信息录入助手。只输出 JSON,不要任何解释或多余文字。"

TRIP_NOTE = "待认领行程,请在「姓名」列填上出行人"


def build_user_prompt():
    return (
        "从下面的微信回执文本和截图里提取信息,严格按给定 JSON 结构输出。\n"
        "\n【人员信息 people】\n"
        "- 可能有多个人(群聊里多人各贴一段),每识别出一个人就在 people 里加一个对象。\n"
        '- 「媒体名称」只取明确标注"媒体名称:"后面的值;聊天气泡上方的发信人昵称/群昵称'
        '(例如"大冰块")不是媒体名称,不要填,判断不了就留空 ""。\n'
        "- 身份证号、银行卡号、手机号、支付宝账号原样照抄,不要改写、补零或加空格。\n"
        "- 收款方式填「银行卡」或「支付宝」;同一人若同时给了银行卡和支付宝,任选其一填入,"
        '并把"收款方式"放进该人的 _uncertain。开户行仅银行卡时填。\n'
        '- 缺失字段填 ""。拿不准的字段名放进该人对象的 _uncertain 数组,如 ["姓名","收款方式"]。\n'
        "\n【行程信息 itineraries】\n"
        "- 来自机票/高铁/行程单截图。一张往返行程单 = 一个 itinerary 对象,含 去程 和/或 返程。\n"
        "- 行程截图通常不含出行人姓名,不要猜是谁(人员匹配交人工),你只把行程本身抽准。\n"
        "- 方式填 飞机/高铁/火车/打车/其他;城市只填城市名(如「北京」);日期 YYYY-MM-DD;时间 24 小时 HH:MM。\n"
        '- 日期若截图未写年份,按最合理年份补全并把该字段(如"去程.日期")放进该 itinerary 的 _uncertain。\n'
        '- 分不清哪程是去程/返程时,把"去程"或"返程"整体放进 _uncertain。\n'
        "\n只输出下面结构的 JSON:\n"
        "{\n"
        '  "people": [\n'
        '    {"媒体名称":"","姓名":"","职位":"","电话":"","身份证号":"","收款方式":"","收款账号":"","开户行":"","_uncertain":[]}\n'
        "  ],\n"
        '  "itineraries": [\n'
        '    {"去程":{"方式":"","日期":"","出发城市":"","到达城市":"","航班车次":"","出发时间":"","到达时间":"","航站楼":""},\n'
        '     "返程":{"方式":"","日期":"","出发城市":"","到达城市":"","航班车次":"","出发时间":"","到达时间":"","航站楼":""},\n'
        '     "_uncertain":[]}\n'
        "  ],\n"
        '  "notes":""\n'
        "}"
    )


class PersonUnit:
    def __init__(self, name, text_files, image_files):
        self.name = name
        self.text_files = text_files
        self.image_files = image_files

    def read_text(self):
        parts = []
        for tf in self.text_files:
            try:
                parts.append(tf.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                parts.append(tf.read_text(encoding="gbk", errors="ignore"))
        return "\n\n".join(p.strip() for p in parts if p.strip())


def _unit_from_dir(name, d):
    texts, images = [], []
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            images.append(f)
        elif ext in TEXT_EXTS:
            texts.append(f)
    return PersonUnit(name, texts, images)


def gather_person_units(activity_dir):
    """活动目录下每个子目录 = 一个单元;若直接放文件,则整目录视为一个单元。"""
    activity_dir = Path(activity_dir)
    subdirs = [d for d in sorted(activity_dir.iterdir()) if d.is_dir()]
    if subdirs:
        units = [_unit_from_dir(d.name, d) for d in subdirs]
    else:
        units = [_unit_from_dir(activity_dir.name, activity_dir)]
    return [u for u in units if (u.text_files or u.image_files)]


def extract_unit(client, unit):
    """返回模型解析后的 dict: {people:[...], itineraries:[...], notes:str}。"""
    text = unit.read_text()
    data, raw = client.vision_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(),
        image_paths=unit.image_files,
        extra_text=text or None,
    )
    return data, raw


# ---- 扁平化 / 拆分为复核表记录 ----

def _empty_row():
    row = {f: "" for f in MEDIA_FIELDS}
    for leg in LEGS:
        for f in LEG_FIELDS:
            row[f"{leg}-{f}"] = ""
    return row


def _fill_media(row, person):
    for f in MEDIA_FIELDS:
        row[f] = str(person.get(f, "") or "").strip()


def _fill_legs(row, itin):
    for leg in LEGS:
        legd = itin.get(leg, {}) or {}
        for f in LEG_FIELDS:
            row[f"{leg}-{f}"] = str(legd.get(f, "") or "").strip()


def _person_uncertain(person):
    cols = set()
    for u in person.get("_uncertain", []) or []:
        last = str(u).split(".")[-1]
        if last in MEDIA_FIELDS:
            cols.add(last)
    return cols


def _itin_uncertain(itin):
    cols = set()
    for u in itin.get("_uncertain", []) or []:
        u = str(u)
        leg = "去程" if "去程" in u else ("返程" if "返程" in u else None)
        if not leg:
            continue
        last = u.split(".")[-1]
        if last in LEG_FIELDS:
            cols.add(f"{leg}-{last}")
        else:  # 整程不确定(如方向)→ 该程全部标黄
            cols.update(f"{leg}-{f}" for f in LEG_FIELDS)
    return cols


def build_records(parsed, source):
    """把模型输出拆成复核表记录列表。

    每条: {'row':{列:值}, 'uncertain':set(列), 'source':str, 'notes':str, 'kind':'person'|'trip'}
    - 单人单元 + 有行程 → 行程直接并入该人(第一段行程);
    - 多人 / 裸行程 → 行程各自成「待认领」记录,姓名列标黄。
    """
    people = parsed.get("people", []) or []
    itins = parsed.get("itineraries", []) or []
    notes = str(parsed.get("notes", "") or "").strip()
    records = []

    if len(people) == 1 and len(itins) >= 1:
        row = _empty_row()
        _fill_media(row, people[0])
        _fill_legs(row, itins[0])
        unc = _person_uncertain(people[0]) | _itin_uncertain(itins[0])
        records.append({"row": row, "uncertain": unc, "source": source, "notes": notes, "kind": "person"})
        rest_itins = itins[1:]
    else:
        for idx, p in enumerate(people):
            row = _empty_row()
            _fill_media(row, p)
            records.append({
                "row": row, "uncertain": _person_uncertain(p), "source": source,
                "notes": notes if idx == 0 else "", "kind": "person",
            })
        rest_itins = itins

    for it in rest_itins:
        row = _empty_row()
        _fill_legs(row, it)
        unc = {"姓名"} | _itin_uncertain(it)
        records.append({"row": row, "uncertain": unc, "source": source, "notes": TRIP_NOTE, "kind": "trip"})

    return records
