"""relay(OpenAI 兼容)视觉客户端。

- chat/completions 接口
- 图片以 data URL(base64)内联传入
- 429/5xx 指数退避重试
- 稳健地从返回里解析 JSON(容忍 ```json 围栏与前后废话)
"""
import base64
import json
import mimetypes
import time
from pathlib import Path

import requests


class RelayError(Exception):
    pass


def image_to_data_url(path):
    path = Path(path)
    mime, _ = mimetypes.guess_type(str(path))
    if not mime or not mime.startswith("image/"):
        mime = "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_json(text):
    """从模型返回里稳健取出 JSON 对象。"""
    if text is None:
        raise RelayError("模型返回为空")
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t[:4].lower() == "json":
            t = t[4:].strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise RelayError(f"无法从模型返回解析出 JSON:\n{text[:500]}")


class LLMClient:
    def __init__(self, base_url, api_key, model, timeout=120, max_retries=3):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    @property
    def endpoint(self):
        b = self.base_url
        if b.endswith("/chat/completions"):
            return b
        if b.endswith("/v1"):
            return b + "/chat/completions"
        return b + "/v1/chat/completions"

    def chat(self, messages, temperature=None):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self.model, "messages": messages}
        # 部分模型(如 Bedrock 上的 Claude)不接受 temperature,默认不发送
        if temperature is not None:
            payload["temperature"] = temperature
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = f"网络错误: {e}"
                time.sleep(min(2 ** attempt, 8))
                continue
            if r.status_code == 200:
                try:
                    data = r.json()
                    return data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError):
                    raise RelayError(f"返回结构异常: {r.text[:500]}")
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(min(2 ** attempt, 8))
                continue
            raise RelayError(f"HTTP {r.status_code}: {r.text[:500]}")
        raise RelayError(f"relay 调用失败(重试 {self.max_retries} 次): {last_err}")

    def vision_json(self, system_prompt, user_prompt, image_paths=None, extra_text=None, temperature=None):
        """发文本 + 若干图片,要求模型返回 JSON。返回 (解析后的 dict, 原始文本)。"""
        content = [{"type": "text", "text": user_prompt}]
        if extra_text:
            content.append({"type": "text", "text": "相关文本:\n" + extra_text})
        for p in (image_paths or []):
            content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        raw = self.chat(messages, temperature=temperature)
        return extract_json(raw), raw
