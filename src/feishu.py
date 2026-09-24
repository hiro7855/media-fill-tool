"""飞书回填底座:纯 Python,不依赖本机 lark-cli。

能力:
- tenant_access_token(内存缓存,按过期刷新)
- 目标链接解析 + wiki 解包 + Bitable/电子表格 类型探测
- Bitable 读字段 / 批量写;电子表格 读表头 / 追加行
"""
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

FEISHU_BASE = "https://open.feishu.cn"

# Bitable 字段 type → 可读名;标注哪些是只读(不可写)
_FIELD_TYPE = {
    1: "文本", 2: "数字", 3: "单选", 4: "多选", 5: "日期时间", 7: "复选框",
    11: "人员", 13: "电话", 15: "超链接", 17: "附件", 18: "单向关联",
    19: "查找引用", 20: "公式", 21: "双向关联", 22: "地理位置", 23: "群组",
    1001: "创建时间", 1002: "最后更新时间", 1003: "创建人", 1004: "修改人", 1005: "自动编号",
}
_READONLY_TYPES = {19, 20, 1001, 1002, 1003, 1004, 1005}

_ERR_HINT = {
    91403: "无权限:请确认该机器人已被加为目标 wiki/表格的协作者,且给了编辑权限。",
    1254045: "字段名不存在:目标表里没有这个字段,请核对映射。",
    1254015: "字段值类型不符:写入值与字段类型不匹配。",
    1254104: "单批超过 200 条:需分批写入。",
    1254291: "并发写入冲突:请串行 + 短暂重试。",
    99991663: "凭证无效:app_id / app_secret 不正确,或应用未启用。",
}


class FeishuError(Exception):
    pass


def _hint(code):
    return _ERR_HINT.get(code, "")


class FeishuClient:
    def __init__(self, app_id, app_secret, timeout=30):
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout
        self._token = None
        self._exp = 0.0

    # ---- 底层 HTTP ----
    def _call(self, method, path, params=None, body=None, auth=True):
        url = FEISHU_BASE + path
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token()}"
        try:
            r = requests.request(method, url, headers=headers, params=params,
                                 json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise FeishuError(f"网络错误: {e}")
        try:
            data = r.json()
        except ValueError:
            raise FeishuError(f"HTTP {r.status_code}: {r.text[:300]}")
        code = data.get("code")
        if code not in (0, None):
            h = _hint(code)
            raise FeishuError(f"飞书接口错误 code={code} msg={data.get('msg')}" + (f"\n  → {h}" if h else ""))
        return data

    def token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        data = self._call(
            "POST", "/open-apis/auth/v3/tenant_access_token/internal",
            body={"app_id": self.app_id, "app_secret": self.app_secret}, auth=False,
        )
        self._token = data["tenant_access_token"]
        self._exp = time.time() + int(data.get("expire", 7200))
        return self._token

    # ---- 链接解析 + 类型探测 ----
    @staticmethod
    def parse_target(url):
        u = urlparse(url)
        seg = [s for s in u.path.split("/") if s]
        kind = token = None
        for i, s in enumerate(seg):
            if s in ("wiki", "base", "sheets", "docx", "doc") and i + 1 < len(seg):
                kind, token = s, seg[i + 1]
                break
        qs = parse_qs(u.query)
        return {
            "kind": kind, "token": token,
            "table_hint": (qs.get("table") or [None])[0],
            "sheet_hint": (qs.get("sheet") or qs.get("view") or [None])[0],
        }

    def resolve_wiki(self, node_token):
        data = self._call("GET", "/open-apis/wiki/v2/spaces/get_node",
                          params={"token": node_token})
        node = data["data"]["node"]
        return node.get("obj_type"), node.get("obj_token")

    def resolve(self, url):
        """解析目标链接为可操作对象:
        {type:'bitable', app_token, table_id, table_name}
        或 {type:'sheets', spreadsheet_token, sheet_id, sheet_title}"""
        p = self.parse_target(url)
        if not p["kind"]:
            raise FeishuError(f"无法识别的飞书链接: {url}")
        kind, token = p["kind"], p["token"]

        if kind == "wiki":
            obj_type, obj_token = self.resolve_wiki(token)
            if obj_type in ("bitable", "base"):
                kind, token = "base", obj_token
            elif obj_type in ("sheet", "sheets"):
                kind, token = "sheets", obj_token
            else:
                raise FeishuError(f"wiki 节点类型暂不支持: obj_type={obj_type}(仅支持 bitable/表格)")

        if kind in ("base", "bitable"):
            return self._resolve_bitable(token, p["table_hint"])
        if kind == "sheets":
            return self._resolve_sheets(token, p["sheet_hint"])
        raise FeishuError(f"暂不支持的目标类型: {kind}")

    def _resolve_bitable(self, app_token, table_hint):
        data = self._call("GET", f"/open-apis/bitable/v1/apps/{app_token}/tables",
                          params={"page_size": 100})
        items = data["data"].get("items", [])
        if not items:
            raise FeishuError("该多维表格里没有数据表。")
        chosen = None
        if table_hint:
            chosen = next((t for t in items if t.get("table_id") == table_hint
                           or t.get("name") == table_hint), None)
        if not chosen:
            chosen = items[0]
        return {"type": "bitable", "app_token": app_token,
                "table_id": chosen["table_id"], "table_name": chosen.get("name", ""),
                "all_tables": [(t["table_id"], t.get("name", "")) for t in items]}

    def _resolve_sheets(self, spreadsheet_token, sheet_hint):
        data = self._call("GET", f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query")
        sheets = data["data"].get("sheets", [])
        if not sheets:
            raise FeishuError("该电子表格里没有工作表。")
        chosen = None
        if sheet_hint:
            chosen = next((s for s in sheets if s.get("sheet_id") == sheet_hint
                           or s.get("title") == sheet_hint), None)
        if not chosen:
            chosen = sheets[0]
        return {"type": "sheets", "spreadsheet_token": spreadsheet_token,
                "sheet_id": chosen["sheet_id"], "sheet_title": chosen.get("title", ""),
                "all_sheets": [(s["sheet_id"], s.get("title", "")) for s in sheets]}

    # ---- 读字段 / 表头 ----
    def bitable_fields(self, app_token, table_id):
        data = self._call("GET", f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                          params={"page_size": 200})
        out = []
        for f in data["data"].get("items", []):
            t = f.get("type")
            out.append({
                "name": f.get("field_name"),
                "type": t,
                "type_name": _FIELD_TYPE.get(t, f"类型{t}"),
                "primary": bool(f.get("is_primary")),
                "editable": t not in _READONLY_TYPES,
            })
        return out

    def sheets_header(self, spreadsheet_token, sheet_id, row=1):
        rng = f"{sheet_id}!A{row}:CZ{row}"
        data = self._call("GET",
                          f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{rng}")
        values = data["data"].get("valueRange", {}).get("values", [[]])
        head = values[0] if values else []
        return [("" if c is None else str(c)).strip() for c in head]

    def describe(self, url):
        """B0 自检:解析 + 探测 + 读字段/表头,返回结构化描述。"""
        target = self.resolve(url)
        if target["type"] == "bitable":
            target["fields"] = self.bitable_fields(target["app_token"], target["table_id"])
        else:
            target["header"] = self.sheets_header(target["spreadsheet_token"], target["sheet_id"])
        return target

    # ---- 写入(B1 用)----
    def bitable_batch_create(self, app_token, table_id, records):
        """records: list of {field_name: cell_value}。单批 ≤200。返回创建的 record 列表。"""
        created = []
        for i in range(0, len(records), 200):
            chunk = records[i:i + 200]
            body = {"records": [{"fields": r} for r in chunk]}
            data = self._call(
                "POST",
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                body=body,
            )
            created.extend(data["data"].get("records", []))
        return created

    def sheets_append(self, spreadsheet_token, sheet_id, rows, ncols):
        """在工作表已有数据下方追加若干行(INSERT_ROWS)。rows: list[list[str]]。"""
        rng = f"{sheet_id}!A1:{_col_letter(ncols)}1"
        body = {"valueRange": {"range": rng, "values": rows}}
        data = self._call(
            "POST",
            f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values_append",
            params={"insertDataOption": "INSERT_ROWS"}, body=body,
        )
        return data


def _col_letter(n):
    """1→A, 26→Z, 27→AA ..."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
