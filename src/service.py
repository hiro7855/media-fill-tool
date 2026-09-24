"""网页后端的编排层(里程碑 C)。

唯一 import 现有业务模块的地方,负责:
- 记录 <-> JSON 互转(set/元组不可直接 json.dumps)
- 逐活动 JSON 持久化(产出/<活动>.records.json,取代 复核_*.xlsx 环节)
- 识别任务注册表(后台线程 + 轮询进度)
- 配置读写、relay/飞书 自检、活动/上传管理、回填试算/写入闸门

控制台日志全 ASCII([OK]/[X]/[!]),不打 emoji(Windows GBK 控制台会崩)。
"""
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ConfigError, load_config, mask_secret, save_config  # noqa: E402
from extract import IMAGE_EXTS, TEXT_EXTS  # noqa: E402

ALLOWED_EXTS = IMAGE_EXTS | TEXT_EXTS
MAX_FILE_BYTES = 20 * 1024 * 1024

_CONFIG_PATH = None

JOBS = {}
_JOBS_LOCK = threading.Lock()
_APPLY_LOCKS = {}
_APPLY_LOCKS_GUARD = threading.Lock()


class ServiceError(Exception):
    def __init__(self, message, code="error"):
        super().__init__(message)
        self.code = code


def init(config_path=None):
    """webapp 启动时调用一次,记住 config.yaml 路径。"""
    global _CONFIG_PATH
    _CONFIG_PATH = config_path
    _cfg()  # 提前校验一次,配置有问题就早点报


def _cfg():
    """每次都重新读,保证「设置」页保存后立即生效。"""
    return load_config(_CONFIG_PATH)


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 记录 <-> JSON(wire 格式:row / uncertain[list] / errors{col:reason} / kind / source / notes)
# ---------------------------------------------------------------------------

def record_to_wire(rec):
    errs = rec.get("errors", {}) or {}
    return {
        "row": dict(rec.get("row", {})),
        "uncertain": sorted(rec.get("uncertain", set()) or set()),
        "errors": {c: (v[1] if isinstance(v, (list, tuple)) else str(v)) for c, v in errs.items()},
        "kind": rec.get("kind", "person"),
        "source": rec.get("source", ""),
        "notes": rec.get("notes", ""),
    }


def _revalidate_wire(records):
    """网页保存回来的记录:服务端重新跑硬校验,回传刷新后的红标(errors)。"""
    from validate import validate_row
    out = []
    for r in (records or []):
        row = {k: ("" if v is None else str(v)) for k, v in (r.get("row") or {}).items()}
        errs = validate_row(row)
        out.append({
            "row": row,
            "uncertain": list(r.get("uncertain") or []),
            "errors": {c: v[1] for c, v in errs.items()},
            "kind": r.get("kind", "person") or "person",
            "source": r.get("source", "") or "",
            "notes": r.get("notes", "") or "",
        })
    return out


# ---------------------------------------------------------------------------
# 持久化:产出/<活动>.records.json
# ---------------------------------------------------------------------------

def _records_path(cfg, activity):
    return cfg.output_dir / f"{activity}.records.json"


def _read_records_file(cfg, activity):
    path = _records_path(cfg, activity)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _save_records_file(cfg, activity, records, applied=None):
    """原子写(临时文件 + os.replace)。applied=None 时保留原有 applied 标记。"""
    path = _records_path(cfg, activity)
    if applied is None:
        prev = _read_records_file(cfg, activity)
        applied = (prev or {}).get("applied", {}) or {}
    payload = {"activity": activity, "updated_at": _now(),
               "applied": applied, "records": records}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return payload


# ---------------------------------------------------------------------------
# 配置读写 + 自检
# ---------------------------------------------------------------------------

def get_config_view():
    cfg = _cfg()
    return {
        "relay": {
            "base_url": cfg.relay_base_url,
            "model": cfg.relay_model,
            "timeout": cfg.relay_timeout,
            "api_key_masked": mask_secret(cfg.relay_key),
            "has_api_key": bool(cfg.relay_key),
        },
        "feishu": {
            "app_id": cfg.feishu_app_id,
            "app_secret_masked": mask_secret(cfg.feishu_app_secret),
            "has_app_secret": bool(cfg.feishu_app_secret),
            "target_url": cfg.target_url,
            "test_url": cfg.test_url,
        },
    }


def update_config(payload):
    """留空的字段保留原值(不覆盖);仅写入用户填了的键。"""
    relay = (payload or {}).get("relay") or {}
    feishu = (payload or {}).get("feishu") or {}
    updates = {}
    r = {}
    if str(relay.get("base_url") or "").strip():
        r["base_url"] = relay["base_url"].strip()
    if str(relay.get("model") or "").strip():
        r["model"] = relay["model"].strip()
    if str(relay.get("api_key") or "").strip():
        r["api_key"] = relay["api_key"].strip()
    if relay.get("timeout"):
        try:
            r["timeout"] = int(relay["timeout"])
        except (TypeError, ValueError):
            pass
    f = {}
    if str(feishu.get("app_id") or "").strip():
        f["app_id"] = feishu["app_id"].strip()
    if str(feishu.get("app_secret") or "").strip():
        f["app_secret"] = feishu["app_secret"].strip()
    if str(feishu.get("target_url") or "").strip():
        f["target_url"] = feishu["target_url"].strip()
    if str(feishu.get("test_url") or "").strip():
        f["test_url"] = feishu["test_url"].strip()
    if r:
        updates["relay"] = r
    if f:
        updates["feishu"] = f
    if updates:
        save_config(updates, _CONFIG_PATH)
    return get_config_view()


def selfcheck_relay():
    cfg = _cfg()
    if not (cfg.relay_base_url and cfg.relay_key and cfg.relay_model):
        return {"ok": False, "detail": "relay 配置不完整(base_url / api_key / model 必填)"}
    from llm_client import LLMClient, RelayError
    from run_extract import _make_test_image
    client = LLMClient(cfg.relay_base_url, cfg.relay_key, cfg.relay_model, timeout=cfg.relay_timeout)
    img = _make_test_image()
    try:
        data, _raw = client.vision_json(
            system_prompt="你是 OCR 助手,只输出 JSON,不要多余文字。",
            user_prompt='读出图片中的文字,输出 {"text": "<图中完整文字>"}。',
            image_paths=[img],
        )
    except RelayError as e:
        return {"ok": False, "detail": f"relay 调用失败: {e}"}
    finally:
        try:
            os.remove(img)
        except OSError:
            pass
    text = str(data.get("text", ""))
    if "4821" in text:
        return {"ok": True, "detail": "relay 视觉链路正常(识别到测试码 4821)"}
    return {"ok": True, "detail": f"relay 有响应,但未读到预期文字,请人工确认返回:{data}"}


def selfcheck_feishu():
    cfg = _cfg()
    if not (cfg.feishu_app_id and cfg.feishu_app_secret and cfg.target_url):
        return {"ok": False, "detail": "飞书配置不完整(app_id / app_secret / target_url 必填)"}
    from feishu import FeishuClient, FeishuError
    client = FeishuClient(cfg.feishu_app_id, cfg.feishu_app_secret)
    try:
        target = client.describe(cfg.target_url)
    except FeishuError as e:
        return {"ok": False, "detail": f"飞书链路失败: {e}"}
    if target["type"] == "sheets":
        return {"ok": True,
                "detail": f"电子表格「{target.get('sheet_title', '')}」,表头 {len(target.get('header', []))} 列"}
    return {"ok": True,
            "detail": f"多维表格,{len(target.get('fields', []))} 个字段(注意:当前回填仅支持电子表格)"}


# ---------------------------------------------------------------------------
# 活动 / 上传
# ---------------------------------------------------------------------------

def _safe_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or ".." in name:
        raise ServiceError("名称不合法。", "bad_name")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ServiceError("名称含非法字符(不能包含 / \\ : * ? \" < > | )。", "bad_name")
    if len(name) > 80:
        raise ServiceError("名称过长。", "bad_name")
    return name


def list_activities():
    cfg = _cfg()
    inp = cfg.input_dir
    out = []
    if inp.exists():
        for d in sorted(inp.iterdir()):
            if not d.is_dir():
                continue
            units = [u for u in sorted(d.iterdir()) if u.is_dir()]
            if units:
                n_files = sum(1 for u in units for f in u.iterdir() if f.is_file())
            else:
                n_files = sum(1 for f in d.iterdir() if f.is_file())
            rec = _read_records_file(cfg, d.name)
            out.append({
                "name": d.name,
                "n_units": len(units),
                "n_files": n_files,
                "has_records": rec is not None,
                "n_records": len(rec.get("records", [])) if rec else 0,
                "applied": (rec or {}).get("applied", {}) or {},
                "updated_at": (rec or {}).get("updated_at", ""),
            })
    return out


def create_activity(name):
    cfg = _cfg()
    name = _safe_name(name)
    (cfg.input_dir / name).mkdir(parents=True, exist_ok=True)
    return {"name": name}


def save_uploads(activity, unit, files):
    """files: list of (filename, bytes)。落到 输入/<活动>/<单元>/。"""
    cfg = _cfg()
    activity = _safe_name(activity)
    unit = _safe_name(unit) if (unit or "").strip() else "默认"
    dest = cfg.input_dir / activity / unit
    dest.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for filename, blob in files:
        base = Path(str(filename)).name
        ext = Path(base).suffix.lower()
        if not base or ".." in base:
            skipped.append({"name": str(filename), "reason": "文件名不合法"})
            continue
        if ext not in ALLOWED_EXTS:
            skipped.append({"name": base, "reason": f"不支持的类型 {ext or '(无扩展名)'}"})
            continue
        if len(blob) > MAX_FILE_BYTES:
            skipped.append({"name": base, "reason": "文件过大(>20MB)"})
            continue
        (dest / base).write_bytes(blob)
        saved.append({"name": base, "unit": unit})
    return {"saved": saved, "skipped": skipped, "unit": unit}


def list_files(activity):
    cfg = _cfg()
    activity = _safe_name(activity)
    d = cfg.input_dir / activity
    units = {}
    if d.exists():
        subs = [u for u in sorted(d.iterdir()) if u.is_dir()]
        if subs:
            for u in subs:
                units[u.name] = [f.name for f in sorted(u.iterdir()) if f.is_file()]
        else:
            loose = [f.name for f in sorted(d.iterdir()) if f.is_file()]
            if loose:
                units["(直接放在活动目录)"] = loose
    return {"activity": activity, "units": units}


# ---------------------------------------------------------------------------
# 识别任务(后台线程 + 轮询)
# ---------------------------------------------------------------------------

def _active_job_for(activity):
    with _JOBS_LOCK:
        for jid, j in JOBS.items():
            if j["activity"] == activity and j["status"] == "running":
                return jid
    return None


def start_extract(activity):
    cfg = _cfg()
    activity = _safe_name(activity)
    if not (cfg.input_dir / activity).exists():
        raise ServiceError(f"活动目录不存在:{activity}", "no_activity")
    busy = _active_job_for(activity)
    if busy:
        raise ServiceError("该活动正在识别中,请等它跑完。", "already_running")
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        JOBS[job_id] = {"job_id": job_id, "activity": activity, "status": "running",
                        "done": 0, "total": 0, "current": "", "logs": [], "error": None,
                        "n_records": 0}
    t = threading.Thread(target=_run_extract_job, args=(job_id, activity), daemon=True)
    t.start()
    return {"job_id": job_id}


def _run_extract_job(job_id, activity):
    def cb(done, total, current, note):
        with _JOBS_LOCK:
            j = JOBS.get(job_id)
            if not j:
                return
            j["done"], j["total"], j["current"] = done, total, current
            if note:
                j["logs"].append(note)
    try:
        cfg = _cfg()
        from run_extract import build_activity_records
        records = build_activity_records(cfg, activity, progress_cb=cb)
        wire = [record_to_wire(r) for r in records]
        _save_records_file(cfg, activity, wire, applied={})  # 新识别 → 清空回填标记
        with _JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["status"] = "done"
                j["n_records"] = len(wire)
                if not wire:
                    j["logs"].append("[!] 没有成功识别到任何记录。")
    except Exception as e:  # noqa: BLE001 后台线程,任何异常都要落到 job 状态
        with _JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["status"] = "error"
                j["error"] = str(e)
                j["logs"].append(f"[X] 识别失败: {e}")


def get_job(job_id):
    with _JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            raise ServiceError("任务不存在或已过期。", "no_job")
        return dict(j)


def get_records(activity):
    cfg = _cfg()
    activity = _safe_name(activity)
    data = _read_records_file(cfg, activity)
    if not data:
        return None
    return data


def save_records(activity, records):
    cfg = _cfg()
    activity = _safe_name(activity)
    revalidated = _revalidate_wire(records)
    payload = _save_records_file(cfg, activity, revalidated)  # 保留原 applied
    return payload


# ---------------------------------------------------------------------------
# 回填:试算 / 写入(共用 run_apply 的安全闸门)
# ---------------------------------------------------------------------------

def resolve_target_url(cfg, target):
    if target == "test":
        return cfg.test_url or cfg.target_url
    return cfg.target_url


def _apply_lock(activity):
    with _APPLY_LOCKS_GUARD:
        lk = _APPLY_LOCKS.get(activity)
        if lk is None:
            lk = threading.Lock()
            _APPLY_LOCKS[activity] = lk
    return lk


def preview_apply(activity, target):
    from feishu import FeishuError
    from run_apply import preview_apply as _preview
    cfg = _cfg()
    activity = _safe_name(activity)
    data = _read_records_file(cfg, activity)
    if not data:
        raise ServiceError("还没有识别结果,请先在「识别」页跑一遍。", "no_records")
    url = resolve_target_url(cfg, target)
    if not url:
        raise ServiceError("未配置目标表链接,请到「设置」填写。", "no_target")
    rows = [r.get("row", {}) for r in data.get("records", [])]
    try:
        pv = _preview(cfg, rows, url)
    except (FeishuError, ValueError) as e:
        raise ServiceError(str(e), "feishu_error")
    pv["target"] = target
    pv["target_url"] = url
    pv["applied"] = data.get("applied", {}) or {}
    return pv


def write_apply(activity, target, force=False):
    from feishu import FeishuError
    from run_apply import write_apply as _write
    cfg = _cfg()
    activity = _safe_name(activity)
    url = resolve_target_url(cfg, target)
    if not url:
        raise ServiceError("未配置目标表链接,请到「设置」填写。", "no_target")
    with _apply_lock(activity):
        data = _read_records_file(cfg, activity)
        if not data:
            raise ServiceError("还没有识别结果,请先在「识别」页跑一遍。", "no_records")
        applied = data.get("applied", {}) or {}
        if applied.get(target) and not force:
            return {"ok": False, "reason": "already_applied", "target": target,
                    "target_url": url, "applied_at": applied[target]}
        rows = [r.get("row", {}) for r in data.get("records", [])]
        try:
            res = _write(cfg, rows, url)
        except FeishuError as e:
            raise ServiceError(f"写入失败: {e}", "feishu_error")
        res["target"] = target
        res["target_url"] = url
        if res.get("ok"):
            applied[target] = _now()
            _save_records_file(cfg, activity, data.get("records", []), applied=applied)
        return res
