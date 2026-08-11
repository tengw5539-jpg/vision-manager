"""
VisionPower 桌面管理器 — 视觉模型配置管理（类似 cc-switch）
============================================================
- 管理 ~/.visionpower/config.json（VisionPower 的视觉模型配置）
- 内置常见视觉模型预设，也可自定义服务商
- 一键测试视觉 API 连通性
- 从 cc-switch 数据库导入已有服务商（可复用其 API Key）
- 支持一键切换模型并持久化到 VisionPower 配置

运行: python server.py
访问: http://127.0.0.1:17910
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

# ---------- 路径 ----------
CONFIG_PATH = Path.home() / ".visionpower" / "config.json"
CC_SWITCH_DB = Path.home() / ".cc-switch" / "cc-switch.db"

# ---------- 内置模型预设 ----------
# (名称, 模型ID, baseUrl, 备注)
VISION_PRESETS = [
    ("Qwen3-VL Flash（阿里百炼）", "qwen3-vl-flash", "https://dashscope.aliyuncs.com/compatible-mode/v1", "推荐：快、便宜、国内直连"),
    ("Qwen3-VL Plus（阿里百炼）", "qwen3-vl-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", "更强，价格更高"),
    ("GLM-4.6V（智谱）", "glm-4.6v", "https://open.bigmodel.cn/api/paas/v4", "智谱视觉模型"),
    ("GLM-5V-Turbo（智谱）", "glm-5v-turbo", "https://open.bigmodel.cn/api/paas/v4", "新一代视觉"),
    ("Doubao Seed 2.1（火山方舟）", "doubao-seed-2-1-turbo-260628", "https://ark.cn-beijing.volces.com/api/v3", "火山引擎"),
    ("MiniMax-M3（国内）", "minimax-m3", "https://api.minimaxi.com/v1", "MiniMax"),
    ("Kimi K2.7 Code（月之暗面）", "kimi-k2.7-code", "https://api.moonshot.cn/v1", "Kimi 视觉"),
    ("GPT-4o（OpenAI）", "gpt-4o", "https://api.openai.com/v1", "海外"),
    ("Gemini 3.6 Flash（Google）", "gemini-3.6-flash", "https://generativelanguage.googleapis.com/v1beta/openai", "海外，有免费档"),
    ("Mimo-V2.5（opencode go 网关）", "mimo-v2.5", "https://opencode.ai/zen/go/v1", "走 opencode go 订阅，已实测支持视觉"),
    ("Mimo-V2-Omni（opencode go 网关）", "mimo-v2-omni", "https://opencode.ai/zen/go/v1", "走 opencode go 订阅，全模态"),
]


def load_config():
    """读取当前 VisionPower 配置"""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    """写回 VisionPower 配置（原子写入）"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


# ---------- cc-switch 集成 ----------
def read_ccswitch_providers():
    """从 cc-switch 数据库读取已有的 Anthropic 协议服务商"""
    if not CC_SWITCH_DB.exists():
        return []
    result = []
    try:
        conn = sqlite3.connect(CC_SWITCH_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, settings_config FROM providers WHERE app_type='claude'"
        ).fetchall()
        for row in rows:
            name = row["name"]
            try:
                cfg = json.loads(row["settings_config"])
                env = cfg.get("env", {})
                base = env.get("ANTHROPIC_BASE_URL", "")
                key = env.get("ANTHROPIC_AUTH_TOKEN", "")
                model = (
                    env.get("ANTHROPIC_MODEL")
                    or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL_NAME")
                    or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                    or ""
                )
                # 只收录有 base + key 的（视觉请求需要真 endpoint）
                if base and key:
                    result.append({
                        "name": name,
                        "base_url": base,
                        "api_key": key,
                        "model": model,
                        "source": "cc-switch",
                    })
            except Exception:
                continue
        conn.close()
    except Exception:
        pass
    return result


def opencode_go_key():
    """从 cc-switch 读取 OpenCode Go 的 key（用于 opencode go 网关预设）"""
    for p in read_ccswitch_providers():
        if "opencode" in p["name"].lower() and "go" in p["name"].lower():
            return p
    return None


# ---------- API ----------
@app.route("/")
def index():
    return send_from_directory(Path(__file__).parent, "index.html")


@app.route("/api/config", methods=["GET"])
def api_config():
    return jsonify({"ok": True, "config": load_config()})


@app.route("/api/presets", methods=["GET"])
def api_presets():
    presets = []
    for name, model, base, note in VISION_PRESETS:
        presets.append({"name": name, "model": model, "base_url": base, "note": note})
    # opencode go 网关预设：如果 cc-switch 里有对应 key，直接填充
    og = opencode_go_key()
    if og:
        presets.append({
            "name": "OpenCode Go 网关（自动填 Key）",
            "model": "mimo-v2.5",
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": og["api_key"],
            "note": "已自动读取 cc-switch 中 OpenCode Go 的 key",
            "source": "cc-switch",
        })
    return jsonify({"ok": True, "presets": presets})


@app.route("/api/ccswitch", methods=["GET"])
def api_ccswitch():
    providers = read_ccswitch_providers()
    return jsonify({"ok": True, "providers": providers})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False, "error": "空请求"}), 400
    # 只保存允许的字段（防未知字段污染）
    allowed = {"apiKey", "model", "baseUrl", "allowedDirs", "maxTokens", "maxImageBytes", "timeoutMs", "cache"}
    cleaned = {k: v for k, v in data.items() if k in allowed and v not in (None, "")}
    # allowedDirs 校验为列表
    if "allowedDirs" in cleaned and not isinstance(cleaned["allowedDirs"], list):
        cleaned["allowedDirs"] = [str(cleaned["allowedDirs"])]
    current = load_config()
    current.update(cleaned)
    save_config(current)
    return jsonify({"ok": True, "config": current})


@app.route("/api/test", methods=["POST"])
def api_test():
    """测试视觉 API 连通性：发送一张 1x1 红点 PNG"""
    data = request.get_json(force=True) or {}
    base_url = (data.get("baseUrl") or "").strip().rstrip("/")
    api_key = (data.get("apiKey") or "").strip()
    model = (data.get("model") or "").strip()

    if not base_url or not api_key or not model:
        return jsonify({"ok": False, "error": "baseUrl / apiKey / model 不能为空"}), 400

    # 1x1 红色 PNG（base64）
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    # 兼容两种 URL 形态：用户可能给根 URL 或完整 endpoint
    if base_url.endswith("/chat/completions"):
        endpoint = base_url
    else:
        endpoint = base_url + "/chat/completions"

    payload = {
        "model": model,
        "max_tokens": 80,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this image? One word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        msg = (body.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content")
        reasoning = msg.get("reasoning_content") or ""
        if isinstance(content, list):
            content = " ".join(str(c.get("text", "")) for c in content)
        # 判断是否真的看到了图（模型会编，但没图会明说看不见）
        if not content:
            return jsonify({"ok": True, "model": model, "note": "连通（空回复，可能 max_tokens 太短）", "raw": str(body)[:300]})
        low = (str(content) + " " + str(reasoning)).lower()
        blind = any(k in low for k in ["can't see", "cannot see", "unable to", "don't have multi", "no multimodal", "no vision", "cannot process image", "can't process", "unsupported image"])
        return jsonify({
            "ok": True,
            "model": model,
            "result": str(content)[:200],
            "vision_ok": not blind,
            "note": "⚠️ 模型可能无视觉能力，返回的是猜测" if blind else "✅ 模型确认有视觉能力",
        })
    except urllib.error.HTTPError as e:
        return jsonify({"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 400


def open_browser():
    time.sleep(1.0)
    try:
        import webbrowser
        webbrowser.open("http://127.0.0.1:17910")
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    print("=" * 50)
    print("VisionPower 桌面管理器已启动")
    print("地址: http://127.0.0.1:17910")
    print("按 Ctrl+C 退出")
    print("=" * 50)
    app.run(host="127.0.0.1", port=17910, debug=False, use_reloader=False)
