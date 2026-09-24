"""配置加载。

config.yaml 与源码分离,含 relay key 与飞书凭证,勿提交到版本库/勿外发。
用 PyYAML 解析,给非技术用户留注释友好的编辑体验。
"""
import re
from pathlib import Path

try:
    import yaml
except ImportError:  # 未装依赖时给出可读提示
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


class ConfigError(Exception):
    pass


def mask_secret(s, keep=4):
    """脱敏展示密钥,避免在日志/控制台回显完整值。"""
    if not s:
        return "(未填写)"
    s = str(s)
    if len(s) <= keep + 2:
        return "***"
    return f"{s[:keep]}...{s[-2:]}"


def load_config(path=None):
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        raise ConfigError(
            f"找不到配置文件: {p}\n"
            "请把 config.example.yaml 复制为 config.yaml 并填写。"
        )
    if yaml is None:
        raise ConfigError("缺少 PyYAML,请先双击运行「安装依赖」脚本(pip install pyyaml)。")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(data, p)


class Config:
    def __init__(self, data, path):
        self.data = data
        self.path = path

    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node if node is not None else default

    # ---- relay ----
    @property
    def relay_base_url(self):
        return self.get("relay", "base_url", default="")

    @property
    def relay_key(self):
        return self.get("relay", "api_key", default="")

    @property
    def relay_model(self):
        return self.get("relay", "model", default="")

    @property
    def relay_timeout(self):
        return int(self.get("relay", "timeout", default=120) or 120)

    # ---- feishu ----
    @property
    def feishu_app_id(self):
        return self.get("feishu", "app_id", default="")

    @property
    def feishu_app_secret(self):
        return self.get("feishu", "app_secret", default="")

    @property
    def target_url(self):
        return self.get("feishu", "target_url", default="")

    @property
    def test_url(self):
        """可选的测试表链接;没配就退回 target_url。"""
        return self.get("feishu", "test_url", default="") or ""

    # ---- paths ----
    @property
    def input_dir(self):
        return ROOT / str(self.get("paths", "input_dir", default="输入"))

    @property
    def output_dir(self):
        return ROOT / str(self.get("paths", "output_dir", default="产出"))


# ---- 写回配置(定点替换标量键,保留注释与其余内容)----

def _fmt_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = "" if v is None else str(v)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _upsert_key(lines, section, key, val):
    sec_re = re.compile(r"^" + re.escape(section) + r"\s*:\s*$")
    key_re = re.compile(r"^(\s+)" + re.escape(key) + r"\s*:\s*.*$")
    sec_idx = None
    for i, ln in enumerate(lines):
        if sec_re.match(ln):
            sec_idx = i
            break
    if sec_idx is None:  # section 不存在则在末尾补
        return lines + [f"{section}:", f'  {key}: {_fmt_value(val)}']
    # section 块结束于下一个顶格(非空白、非注释)行
    end = len(lines)
    for j in range(sec_idx + 1, len(lines)):
        ln = lines[j]
        if ln and not ln[0].isspace() and not ln.lstrip().startswith("#"):
            end = j
            break
    for j in range(sec_idx + 1, end):
        m = key_re.match(lines[j])
        if m:
            lines[j] = f"{m.group(1)}{key}: {_fmt_value(val)}"
            return lines
    lines.insert(sec_idx + 1, f'  {key}: {_fmt_value(val)}')
    return lines


def save_config(updates, path=None):
    """updates: {'relay': {...}, 'feishu': {...}}。只写入提供的叶子键,
    值为 None 的键跳过(用于「留空则保留原值」),其余注释/键顺序保持不变。"""
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        raise ConfigError(f"找不到配置文件: {p}")
    lines = p.read_text(encoding="utf-8").splitlines()
    for section, kv in (updates or {}).items():
        for key, val in (kv or {}).items():
            if val is None:
                continue
            lines = _upsert_key(lines, section, key, val)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
