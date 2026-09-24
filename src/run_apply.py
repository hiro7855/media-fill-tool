"""回填入口(里程碑 B)。

用法:
  py -3 src/run_apply.py --selfcheck   # B0: 飞书链路自检(拿 token → 解链接 → 探测类型 → 读字段)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ConfigError, load_config, mask_secret  # noqa: E402
from feishu import FeishuClient, FeishuError  # noqa: E402


def selfcheck(cfg):
    print("== 飞书配置 ==")
    print(f"  app_id       : {cfg.feishu_app_id}")
    print(f"  app_secret   : {mask_secret(cfg.feishu_app_secret)}")
    print(f"  target_url   : {cfg.target_url}")
    print()

    missing = [n for n, v in (
        ("app_id", cfg.feishu_app_id),
        ("app_secret", cfg.feishu_app_secret),
        ("target_url", cfg.target_url),
    ) if not v]
    if missing:
        print(f"[X] 飞书配置不完整,缺: {', '.join(missing)}")
        return 1

    client = FeishuClient(cfg.feishu_app_id, cfg.feishu_app_secret)

    print("== 步骤1/3:获取 tenant_access_token ==")
    try:
        client.token()
    except FeishuError as e:
        print(f"[X] 取 token 失败: {e}")
        return 1
    print("[OK] token 获取成功\n")

    print("== 步骤2/3:解析链接 + 探测类型 ==")
    try:
        p = client.parse_target(cfg.target_url)
        print(f"  链接解析: kind={p['kind']} token={p['token']} "
              f"table_hint={p['table_hint']} sheet_hint={p['sheet_hint']}")
        target = client.resolve(cfg.target_url)
    except FeishuError as e:
        print(f"[X] 解析/探测失败: {e}")
        return 1

    if target["type"] == "bitable":
        print(f"[OK] 目标是【多维表格 Bitable】 app_token={target['app_token']}")
        print(f"     选中数据表: {target['table_name']} ({target['table_id']})")
        if len(target.get("all_tables", [])) > 1:
            print("     该多维表格所有数据表:")
            for tid, name in target["all_tables"]:
                print(f"       - {name} ({tid})")
    else:
        print(f"[OK] 目标是【电子表格 Sheets】 token={target['spreadsheet_token']}")
        print(f"     选中工作表: {target['sheet_title']} ({target['sheet_id']})")
    print()

    print("== 步骤3/3:读取目标字段 ==")
    try:
        target = client.describe(cfg.target_url)
    except FeishuError as e:
        print(f"[X] 读字段失败: {e}")
        return 1

    if target["type"] == "bitable":
        fields = target["fields"]
        print(f"[OK] 共 {len(fields)} 个字段:")
        for f in fields:
            flags = []
            if f["primary"]:
                flags.append("主字段")
            if not f["editable"]:
                flags.append("只读")
            tail = ("  [" + "/".join(flags) + "]") if flags else ""
            print(f"     - {f['name']}  <{f['type_name']}>{tail}")
    else:
        head = target["header"]
        print(f"[OK] 表头 {len(head)} 列: {head}")

    print("\n[OK] B0 三步全部通过。可以进 B1(单人回填)。")
    return 0


def _latest_review(cfg):
    out = cfg.output_dir
    if not out.exists():
        return None
    xs = sorted(out.glob("复核_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return xs[0] if xs else None


def preview_apply(cfg, rows, target_url):
    """试算:合并出席人+行程 → 按列位置拼行 → 返回结构化落点预览(不写入)。

    抛 FeishuError(链路/权限)或 ValueError(类型不支持)。
    """
    from feishu import FeishuClient, _col_letter
    from mapping import AI_COLS, build_sheet_row, check_header, merge_records

    client = FeishuClient(cfg.feishu_app_id, cfg.feishu_app_secret)
    target = client.describe(target_url)
    if target["type"] != "sheets":
        raise ValueError(f"当前回填仅支持电子表格,目标类型为 {target['type']}")
    header = target["header"]
    mismatches = check_header(header)
    persons, unassigned = merge_records(rows)

    def cells_of(rec):
        srow = build_sheet_row(rec)
        out = []
        for idx in AI_COLS:
            v = srow[idx - 1]
            if not v:
                continue
            h = header[idx - 1] if idx - 1 < len(header) else ""
            out.append({"col": idx, "letter": _col_letter(idx),
                        "header": str(h).replace("\n", ""), "value": v})
        return out

    return {
        "type": "sheets",
        "sheet_title": target.get("sheet_title", ""),
        "spreadsheet_token": target["spreadsheet_token"],
        "sheet_id": target["sheet_id"],
        "header_ok": not mismatches,
        "mismatches": mismatches,
        "persons": [{"who": (p.get("姓名") or "(未填姓名)"), "cells": cells_of(p)} for p in persons],
        "unassigned": [{"cells": cells_of(t)} for t in unassigned],
        "n_persons": len(persons),
        "n_unassigned": len(unassigned),
    }


def write_apply(cfg, rows, target_url):
    """真正写入:describe → 锚点校验 → 追加。返回 {ok, appended_rows, sheet_title} 或 {ok:False, reason}。"""
    from feishu import FeishuClient
    from mapping import NCOLS, build_sheet_row, check_header, merge_records

    client = FeishuClient(cfg.feishu_app_id, cfg.feishu_app_secret)
    target = client.describe(target_url)
    if target["type"] != "sheets":
        return {"ok": False, "reason": "unsupported_type"}
    if check_header(target["header"]):
        return {"ok": False, "reason": "header_mismatch"}
    persons, _unassigned = merge_records(rows)
    if not persons:
        return {"ok": False, "reason": "no_persons"}
    sheet_rows = [build_sheet_row(p) for p in persons]
    client.sheets_append(target["spreadsheet_token"], target["sheet_id"], sheet_rows, NCOLS)
    return {"ok": True, "appended_rows": len(sheet_rows), "sheet_title": target.get("sheet_title", "")}


def run_apply(cfg, review_file=None, do_write=False):
    from feishu import FeishuError
    from review_xlsx import read_review

    path = Path(review_file) if review_file else _latest_review(cfg)
    if not path or not path.exists():
        print("[X] 找不到复核表。请先跑识别生成 产出/复核_*.xlsx,或用 --file 指定。")
        return 1
    print(f"复核表: {path}\n")

    rows = read_review(path)
    try:
        pv = preview_apply(cfg, rows, cfg.target_url)
    except (FeishuError, ValueError) as e:
        print(f"[X] 目标表探测/校验失败: {e}")
        return 1

    print(f"合并结果 → 出席人 {pv['n_persons']} 人 / 未认领行程 {pv['n_unassigned']} 条")
    if pv["n_unassigned"]:
        print(f"[!] 有 {pv['n_unassigned']} 条行程没填出行人姓名,本次不会写入。请在复核表补出行人后重跑。")
    if not pv["header_ok"]:
        print("[X] 目标表列结构与预期不符,为避免写错列已中止:")
        for idx, expect, actual in pv["mismatches"]:
            print(f"     第{idx}列 期望含「{expect}」,实际「{actual}」")
        return 1
    if not pv["n_persons"]:
        print("[X] 没有可写入的出席人记录。")
        return 1
    print(f"[OK] 目标表锚点列校验通过(工作表「{pv['sheet_title']}」)\n")

    print("== 试算预览(AI 将写入的列)==")
    for p in pv["persons"]:
        print(f"\n  ▶ 出席人: {p['who']}")
        for c in p["cells"]:
            print(f"      {c['letter']}列 [{c['header']}] = {c['value']}")
    print()

    if not do_write:
        print("== 试算完成,未写入任何数据 ==")
        print("确认无误后,加 --write 才会真正追加到目标表。")
        return 0

    print(f"== 写入:向工作表「{pv['sheet_title']}」追加 {pv['n_persons']} 行 ==")
    try:
        res = write_apply(cfg, rows, cfg.target_url)
    except FeishuError as e:
        print(f"[X] 写入失败: {e}")
        return 1
    if not res.get("ok"):
        print(f"[X] 未写入: {res.get('reason')}")
        return 1
    print(f"[OK] 已追加 {res['appended_rows']} 行。请到飞书表核对。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="飞书回填")
    ap.add_argument("--selfcheck", action="store_true", help="飞书链路自检(只读)")
    ap.add_argument("--file", default=None, help="指定复核表 xlsx(默认取产出目录最新)")
    ap.add_argument("--write", action="store_true", help="真正写入(默认只试算不写)")
    ap.add_argument("--config", default=None, help="指定 config.yaml 路径")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}")
        return 2

    if args.selfcheck:
        return selfcheck(cfg)

    return run_apply(cfg, review_file=args.file, do_write=args.write)


if __name__ == "__main__":
    sys.exit(main())
