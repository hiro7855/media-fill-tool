"""本地网页服务(里程碑 C)。

用法:
  py -3 src/webapp.py --serve                # 选端口 → 延时开浏览器 → 只绑 127.0.0.1
  py -3 src/webapp.py --serve --port 8765 --no-browser --config path/to/config.yaml

只绑 127.0.0.1(不绑 0.0.0.0):规避 Windows 防火墙弹窗与局域网暴露。
控制台输出全中文/ASCII,禁 emoji(GBK 控制台会崩)。
"""
import argparse
import socket
import sys
import threading
from functools import wraps
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

import service  # noqa: E402
from config import ConfigError  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = Flask(__name__, static_folder=None)
try:
    app.json.ensure_ascii = False  # 让返回的中文可读(Flask 2.2+)
except Exception:  # noqa: BLE001 老版本没有该属性,忽略
    pass


def api(fn):
    """统一把 service 层异常转成 JSON 错误响应。"""
    @wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except service.ServiceError as e:
            status = 409 if e.code == "already_running" else 400
            return jsonify({"error": str(e), "code": e.code}), status
        except ConfigError as e:
            return jsonify({"error": str(e), "code": "config"}), 400
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e), "code": "internal"}), 500
    return wrapper


# ---- 设置 ----
@app.get("/api/config")
@api
def cfg_get():
    return jsonify(service.get_config_view())


@app.post("/api/config")
@api
def cfg_post():
    return jsonify(service.update_config(request.get_json(force=True) or {}))


@app.post("/api/selfcheck/relay")
@api
def sc_relay():
    return jsonify(service.selfcheck_relay())


@app.post("/api/selfcheck/feishu")
@api
def sc_feishu():
    return jsonify(service.selfcheck_feishu())


# ---- 活动 / 上传 ----
@app.get("/api/activities")
@api
def acts_list():
    return jsonify({"activities": service.list_activities()})


@app.post("/api/activities")
@api
def acts_create():
    body = request.get_json(force=True) or {}
    return jsonify(service.create_activity(body.get("name", "")))


@app.post("/api/activities/<name>/upload")
@api
def acts_upload(name):
    unit = request.form.get("unit", "")
    files = [(fs.filename, fs.read()) for fs in request.files.getlist("files")]
    if not files:
        raise service.ServiceError("没有收到文件。", "no_files")
    return jsonify(service.save_uploads(name, unit, files))


@app.get("/api/activities/<name>/files")
@api
def acts_files(name):
    return jsonify(service.list_files(name))


# ---- 识别 ----
@app.post("/api/activities/<name>/extract")
@api
def acts_extract(name):
    return jsonify(service.start_extract(name))


@app.get("/api/jobs/<job_id>")
@api
def job_get(job_id):
    return jsonify(service.get_job(job_id))


@app.get("/api/activities/<name>/records")
@api
def recs_get(name):
    data = service.get_records(name)
    if data is None:
        return jsonify({"records": [], "applied": {}, "has_records": False})
    data["has_records"] = True
    return jsonify(data)


@app.put("/api/activities/<name>/records")
@api
def recs_put(name):
    body = request.get_json(force=True) or {}
    return jsonify(service.save_records(name, body.get("records", [])))


# ---- 回填 ----
@app.post("/api/activities/<name>/apply/preview")
@api
def apply_preview(name):
    body = request.get_json(force=True) or {}
    return jsonify(service.preview_apply(name, body.get("target", "test")))


@app.post("/api/activities/<name>/apply/write")
@api
def apply_write(name):
    body = request.get_json(force=True) or {}
    if not body.get("confirm"):
        raise service.ServiceError("写入需要显式确认(confirm=true)。", "need_confirm")
    return jsonify(service.write_apply(name, body.get("target", "test"), force=bool(body.get("force"))))


# ---- 静态前端 ----
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:fname>")
def assets(fname):
    return send_from_directory(WEB_DIR, fname)


def _pick_port(preferred=8765):
    """优先用 preferred;占用则退回系统分配的临时端口。"""
    for port in (preferred, 0):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            actual = s.getsockname()[1]
        except OSError:
            s.close()
            continue
        s.close()
        return actual
    return preferred


def serve(config_path=None, port=None, open_browser=True):
    try:
        service.init(config_path)
    except ConfigError as e:
        print(f"[X] 配置有问题,无法启动: {e}")
        print("    请把 config.example.yaml 复制为 config.yaml 并填写后重试。")
        return 2
    port = port or _pick_port(8765)
    url = f"http://127.0.0.1:{port}/"
    line = "=" * 52
    print(line)
    print("  媒介助手已启动")
    print(f"  请在浏览器打开: {url}")
    print("  (若没自动弹出,手动复制上面地址到浏览器)")
    print("  关闭这个窗口即可停止服务。")
    print(line)
    if open_browser:
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
    return 0


def main():
    ap = argparse.ArgumentParser(description="媒介助手本地网页服务")
    ap.add_argument("--serve", action="store_true", help="启动本地网页服务")
    ap.add_argument("--port", type=int, default=None, help="指定端口(默认 8765,占用则临时端口)")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--config", default=None, help="指定 config.yaml 路径")
    args = ap.parse_args()

    if not args.serve:
        ap.print_help()
        return 0
    return serve(config_path=args.config, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
