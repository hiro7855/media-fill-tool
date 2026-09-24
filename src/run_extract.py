"""识别入口(里程碑 A)。

用法:
  py -3 src/run_extract.py --selfcheck    # A0: relay 视觉冒烟测试
  py -3 src/run_extract.py                # A1 起:遍历输入目录做提取(逐步补全)
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ConfigError, load_config, mask_secret  # noqa: E402
from llm_client import LLMClient, RelayError  # noqa: E402


def _make_test_image():
    """生成一张带已知文字的测试图,用于冒烟测试视觉链路。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (480, 140), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 55), "SMOKE TEST CODE 4821", fill="black")
    fd, name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(name)
    return name


def selfcheck(cfg):
    print("== 配置 ==")
    print(f"  relay base_url : {cfg.relay_base_url}")
    print(f"  relay model    : {cfg.relay_model}")
    print(f"  relay key      : {mask_secret(cfg.relay_key)}")
    print()

    missing = [n for n, v in (
        ("base_url", cfg.relay_base_url),
        ("api_key", cfg.relay_key),
        ("model", cfg.relay_model),
    ) if not v]
    if missing:
        print(f"[X] relay 配置不完整,缺: {', '.join(missing)}")
        return 1

    print("== relay 视觉冒烟测试(发一张测试图,期望回读出 4821)==")
    client = LLMClient(cfg.relay_base_url, cfg.relay_key, cfg.relay_model, timeout=cfg.relay_timeout)
    img = _make_test_image()
    try:
        data, raw = client.vision_json(
            system_prompt="你是 OCR 助手,只输出 JSON,不要多余文字。",
            user_prompt='读出图片中的文字,输出 {"text": "<图中完整文字>"}。',
            image_paths=[img],
        )
    except RelayError as e:
        print(f"[X] relay 调用失败: {e}")
        return 1
    finally:
        try:
            os.remove(img)
        except OSError:
            pass

    text = str(data.get("text", ""))
    print(f"  模型返回: {data}")
    if "4821" in text:
        print("[OK] relay 视觉链路通过 (识别到 4821)")
        return 0
    print("[!] relay 有响应,但未读到预期文字,请人工确认返回内容是否合理。")
    return 0


def build_activity_records(cfg, activity, progress_cb=None):
    """对一个活动目录做识别,返回复核记录列表(每条已带 errors)。

    progress_cb(done, total, current, note) 可选:每处理完一个单元回调一次,
    供网页显示进度/日志;note 为该单元的中文摘要或错误信息。
    """
    from extract import build_records, extract_unit, gather_person_units
    from llm_client import LLMClient, RelayError
    from validate import validate_row

    act_dir = cfg.input_dir / activity
    if not act_dir.exists():
        raise FileNotFoundError(f"活动目录不存在: {act_dir}")
    units = gather_person_units(act_dir)
    total = len(units)
    if progress_cb:
        progress_cb(0, total, "", f"共 {total} 个单元")
    client = LLMClient(cfg.relay_base_url, cfg.relay_key, cfg.relay_model, timeout=cfg.relay_timeout)

    records = []
    for i, u in enumerate(units):
        if progress_cb:
            progress_cb(i, total, u.name, f"识别 {u.name}(图 {len(u.image_files)} / 文本 {len(u.text_files)})")
        try:
            parsed, _raw = extract_unit(client, u)
        except RelayError as e:
            if progress_cb:
                progress_cb(i + 1, total, u.name, f"[X] {u.name} 识别失败: {e}")
            continue
        recs = build_records(parsed, u.name)
        for r in recs:
            r["errors"] = validate_row(r["row"])
        records.extend(recs)
        if progress_cb:
            n_person = sum(1 for r in recs if r.get("kind") != "trip")
            n_trip = sum(1 for r in recs if r.get("kind") == "trip")
            n_red = sum(len(r.get("errors", {})) for r in recs)
            n_yellow = sum(len(r.get("uncertain", set())) for r in recs)
            progress_cb(i + 1, total, u.name,
                        f"[OK] {u.name}: 人 {n_person} / 待认领行程 {n_trip} / 标红 {n_red} / 标黄 {n_yellow}")
    return records


def run_extract(cfg, activity=None):
    from review_xlsx import write_review

    input_dir = cfg.input_dir
    if not input_dir.exists():
        print(f"[X] 输入目录不存在: {input_dir}\n请在其中按「活动/人」放入文本(.txt)和截图。")
        return 1

    activities = [d for d in sorted(input_dir.iterdir()) if d.is_dir()]
    if activity:
        activities = [d for d in activities if d.name == activity]
    if not activities:
        print(f"[X] {input_dir} 下没有活动子目录。请建 输入/<活动名>/ 再放资料。")
        return 1

    rc = 0
    for act in activities:
        def _cb(done, total, current, note):
            if note:
                print(f"  {note}")
        print(f"== 活动: {act.name} ==")
        records = build_activity_records(cfg, act.name, progress_cb=_cb)
        if records:
            out = cfg.output_dir / f"复核_{act.name}.xlsx"
            write_review(records, out)
            print(f"  -> 复核表已生成: {out}")
        else:
            print(f"[!] 活动「{act.name}」没有成功识别的记录。")
            rc = 1
    return rc


def main():
    ap = argparse.ArgumentParser(description="媒介信息识别")
    ap.add_argument("--selfcheck", action="store_true", help="只做 relay 连通性冒烟测试")
    ap.add_argument("--activity", default=None, help="只处理指定活动子目录")
    ap.add_argument("--config", default=None, help="指定 config.yaml 路径")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}")
        return 2

    if args.selfcheck:
        return selfcheck(cfg)

    return run_extract(cfg, activity=args.activity)


if __name__ == "__main__":
    sys.exit(main())
