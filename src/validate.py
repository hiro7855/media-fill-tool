"""硬规则校验:手机号、身份证(含校验位)、银行卡(Luhn)、日期、时间。

返回值约定:每个校验函数无误返回 None,有误返回中文原因字符串。
"""
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fields import LEGS  # noqa: E402

_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]


def validate_phone(s):
    s = (s or "").strip()
    if not s:
        return None
    return None if re.fullmatch(r"1[3-9]\d{9}", s) else "手机号应为 11 位数字且以 1[3-9] 开头"


def validate_idcard(s):
    s = (s or "").strip().upper()
    if not s:
        return None
    if not re.fullmatch(r"\d{17}[\dX]", s):
        return "身份证应为 18 位(末位可为 X)"
    try:
        datetime.strptime(s[6:14], "%Y%m%d")
    except ValueError:
        return "身份证中的出生日期不合法"
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    if _ID_CHECK[total % 11] != s[17]:
        return "身份证校验位不正确"
    return None


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_payment(method, account):
    account = (account or "").strip()
    if not account:
        return None
    m = method or ""
    if "银行" in m or "卡" in m:
        digits = re.sub(r"\D", "", account)
        if not (13 <= len(digits) <= 19):
            return "银行卡号位数异常(通常 16-19 位)"
        if not luhn_ok(digits):
            return "银行卡号未通过 Luhn 校验"
    return None


def validate_date(s):
    s = (s or "").strip()
    if not s:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "日期格式应为 YYYY-MM-DD"
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return None
    except ValueError:
        return "日期不合法"


def validate_time(s):
    s = (s or "").strip()
    if not s:
        return None
    return None if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", s) else "时间格式应为 HH:MM(24 小时制)"


def validate_row(row):
    """返回 {列名: ('error', 原因)},仅包含有硬错误的列。"""
    errs = {}

    def put(col, reason):
        if reason:
            errs[col] = ("error", reason)

    put("电话", validate_phone(row.get("电话", "")))
    put("身份证号", validate_idcard(row.get("身份证号", "")))
    put("收款账号", validate_payment(row.get("收款方式", ""), row.get("收款账号", "")))
    for leg in LEGS:
        put(f"{leg}-日期", validate_date(row.get(f"{leg}-日期", "")))
        put(f"{leg}-出发时间", validate_time(row.get(f"{leg}-出发时间", "")))
        put(f"{leg}-到达时间", validate_time(row.get(f"{leg}-到达时间", "")))
    return errs
