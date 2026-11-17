#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为作品集补充**真实**的 Streamlit 页面截图。

流程：
1. 探测本机 Microsoft Edge / Google Chrome 可执行文件；
2. 在不与 8000/8501 冲突的端口上启动独立的 uvicorn 与 streamlit 进程
   （后端使用临时目录中的独立数据库，绝不触碰用户已在运行的服务与数据）；
3. 等待后端 /api/health 与前端 /_stcore/health 就绪；
4. 用无头浏览器逐一访问 st.navigation 页面并截图；
5. 校验图片确实渲染成功（非空白、非重复默认页），**仅保留真实成功的图片**；
6. 关闭本次启动的全部进程，并写出 docs/screenshots/README.md。

所有提示均为中文。若浏览器不可用或页面渲染失败，会如实输出错误原因，
不生成任何占位图或伪造图片；docs/screenshots/ 下只会出现真实渲染成功的 PNG。

用法：
    python scripts/capture_screenshots.py
    python scripts/capture_screenshots.py --backend-port 8020 --frontend-port 8520
"""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "screenshots"

# st.Page 未显式指定 url_path 时，由页面文件名推断（见 streamlit/navigation/page.py）。
# 默认页（default=True）固定为根路径 "/"。
PAGES: list[tuple[str, str, str]] = [
    ("01_智能助手", "/", "智能助手（默认页）"),
    ("02_知识库管理", "/knowledge", "知识库管理"),
    ("03_检索调试", "/retrieval", "检索调试"),
    ("04_Agent工具管理", "/tools", "Agent 工具管理"),
    ("05_RAG评估中心", "/evaluation", "RAG 评估中心"),
]

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CAPTURE_WIDTH, CAPTURE_HEIGHT = 1440, 1000


def log(message: str) -> None:
    print(message, flush=True)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def pick_port(preferred: int) -> int:
    """优先使用 preferred；若被占用则向后顺延，避免破坏已有服务。"""
    port = preferred
    while not port_is_free(port):
        log(f"[端口] {port} 已被占用，顺延至 {port + 1}")
        port += 1
        if port > preferred + 100:
            raise RuntimeError("未找到可用端口，请通过 --backend-port / --frontend-port 指定。")
    return port


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def detect_browser() -> str | None:
    """返回探测到的浏览器绝对路径，找不到返回 None。"""
    log("[探测] 正在查找 Microsoft Edge / Google Chrome 可执行文件……")
    for name in ("SCREENSHOT_BROWSER", "EDGE_PATH", "CHROME_PATH"):
        value = os.environ.get(name, "").strip().strip('"')
        if value and Path(value).is_file():
            log(f"[探测] 由环境变量 {name} 指定：{value}")
            return value
    for candidate in BROWSER_CANDIDATES:
        if candidate and Path(candidate).is_file():
            log(f"[探测] 找到浏览器：{candidate}")
            return candidate
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            log(f"[探测] 由 PATH 找到浏览器：{found}")
            return found
    log("[错误] 未探测到 Edge / Chrome 可执行文件。")
    log("        请安装 Microsoft Edge 或 Google Chrome，或用 SCREENSHOT_BROWSER 指定浏览器绝对路径。")
    return None


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def wait_health(url: str, label: str, proc: subprocess.Popen, log_path: Path, timeout: int = 90) -> bool:
    """轮询健康接口；进程提前退出时立即给出中文错误与日志尾部。"""
    log(f"[等待] {label}：{url}")
    deadline = time.time() + timeout
    last_report = 0.0
    while time.time() < deadline:
        if proc.poll() is not None:
            log(f"[错误] {label} 进程提前退出（退出码 {proc.returncode}）。日志尾部：")
            log(tail_text(log_path))
            return False
        if http_ok(url):
            log(f"[就绪] {label} 已健康。")
            return True
        now = time.time()
        if now - last_report >= 5:
            log(f"[等待] {label} 尚未就绪，继续等待……（剩余 {int(deadline - now)} 秒）")
            last_report = now
        time.sleep(0.6)
    log(f"[错误] 等待 {label} 健康超时（{timeout} 秒）。日志尾部：")
    log(tail_text(log_path))
    return False


def tail_text(path: Path, lines: int = 25) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "（无日志）"
    rows = [row for row in content.splitlines() if row.strip()]
    return "\n".join(f"        {row}" for row in rows[-lines:]) or "（日志为空）"


def spawn(command: list[str], env: dict[str, str], log_path: Path, label: str) -> subprocess.Popen:
    log(f"[启动] {label}：{' '.join(command)}")
    handle = log_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=NO_WINDOW,
    )
    return proc


def stop_process(proc: subprocess.Popen | None, label: str) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        log(f"[清理] {label} 已自行退出（退出码 {proc.returncode}）。")
        return
    log(f"[清理] 正在停止{label}（PID {proc.pid}）……")
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        log(f"[清理] {label} 未在 8 秒内结束，强制结束进程树。")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, creationflags=NO_WINDOW,
            )
        else:
            proc.kill()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
    log(f"[清理] {label} 已停止。")


def validate_png(path: Path) -> dict:
    """用 Pillow 判断图片是否为真实渲染：非空白、尺寸合理、有足够内容。"""
    from PIL import Image, ImageStat

    result: dict = {"ok": False, "reason": "", "size": (0, 0), "bytes": 0,
                    "stddev": 0.0, "ink_ratio": 0.0, "sample": None}
    try:
        size_bytes = path.stat().st_size
    except OSError:
        result["reason"] = "截图文件不存在"
        return result
    result["bytes"] = size_bytes
    if size_bytes < 3000:
        result["reason"] = f"截图文件过小（{size_bytes} 字节），疑似未渲染"
        return result
    try:
        with Image.open(path) as raw:
            raw.load()  # 强制解码，损坏的 PNG 会在此抛错
            result["size"] = raw.size
            image = raw.convert("RGB")
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            stddev = stat.stddev[0]
            small = gray.resize((240, 160))
            if hasattr(small, "get_flattened_data"):
                pixels = list(small.get_flattened_data())
            else:  # 兼容旧版 Pillow
                pixels = list(small.getdata())
            ink = sum(1 for value in pixels if value < 240) / len(pixels)
    except Exception as exc:
        result["reason"] = f"PNG 无法解码：{exc}"
        return result
    result["stddev"] = stddev
    result["ink_ratio"] = ink
    result["sample"] = pixels
    if stddev < 6:
        result["reason"] = f"画面几乎纯色（灰度标准差 {stddev:.1f}），疑似空白或未渲染"
        return result
    if ink < 0.005:
        result["reason"] = f"有效内容占比过低（{ink * 100:.2f}%），疑似空白页"
        return result
    result["ok"] = True
    return result


def mean_abs_diff(a: list[int], b: list[int]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def wait_for_screenshot(path: Path, timeout: float) -> bool:
    """Windows 上浏览器主程序会立即返回，截图由子进程异步写出，需轮询等待。"""
    deadline = time.time() + timeout
    last_size = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0:
            stable = stable + 1 if size == last_size else 0
            last_size = size
            if stable >= 4:  # 连续约 1.6 秒大小不变，视为写入完成
                return True
        time.sleep(0.4)
    return path.exists() and path.stat().st_size > 0


def capture(browser: str, url: str, temp_png: Path, profile_dir: Path,
            budget_ms: int, temp_dir: Path) -> tuple[bool, str, str]:
    """调用无头浏览器截图；依次尝试新旧 headless 模式与是否使用虚拟时间预算。"""
    # budget=0 表示不注入 --virtual-time-budget（部分 SPA 在虚拟时间下反而渲染不全）
    attempts: list[tuple[str, int]] = [
        ("--headless=new", budget_ms),
        ("--headless", budget_ms),
        ("--headless=new", 0),
    ]
    for index, (headless_flag, budget) in enumerate(attempts):
        if temp_png.exists():
            temp_png.unlink()
        command = [
            browser,
            headless_flag,
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={CAPTURE_WIDTH},{CAPTURE_HEIGHT}",
        ]
        if budget > 0:
            command.append(f"--virtual-time-budget={budget}")
        command += [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            f"--screenshot={temp_png}",
            url,
        ]
        log(f"[截图] 尝试 {index + 1}/{len(attempts)}（{headless_flag}，"
            f"虚拟时间预算 {budget or '无'}）：{' '.join(command)}")
        error_log = temp_dir / "browser_stderr.txt"
        try:
            with error_log.open("w", encoding="utf-8", errors="replace") as handle:
                proc = subprocess.Popen(
                    command, stdout=handle, stderr=subprocess.STDOUT,
                    creationflags=NO_WINDOW,
                )
            # 不能用 subprocess.run 后立即判断：Windows 浏览器启动器会立刻退出，
            # 真正的截图由子进程稍后异步写出。
            if not wait_for_screenshot(temp_png, max(30.0, budget / 1000 + 30)):
                log("[截图] 等待截图文件超时。")
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            info = validate_png(temp_png)
            if info["ok"]:
                log(f"[截图] 成功：{info['size'][0]}x{info['size'][1]}，"
                    f"{info['bytes']} 字节，灰度标准差 {info['stddev']:.1f}，"
                    f"有效内容占比 {info['ink_ratio'] * 100:.1f}%")
                return True, "", ""  # CLI 模式拿不到 DOM 文本，靠像素差兜底判定
            log(f"[截图] 未得到有效画面：{info['reason']}（启动器退出码 {proc.returncode}）")
            tail = tail_text(error_log, 12)
            if tail.strip():
                log(f"[截图] 浏览器输出尾部：\n{tail}")
        except Exception as exc:
            log(f"[截图] 调用异常：{exc}")
    return False, "无头浏览器未能在任何一种 headless 模式下渲染出有效画面", ""


class HeadlessSession:
    """通过 Chrome DevTools Protocol 控制一个无头 Edge/Chrome 实例。

    相比命令行 ``--screenshot``，CDP 可以在**真实时间**里等待 Streamlit 通过
    websocket 完成渲染后再截图，避免截到空白的加载骨架。
    """

    def __init__(self, browser: str, temp_dir: Path):
        self.browser = browser
        self.temp_dir = temp_dir
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self.browser_ws_url = ""
        self._log_path = temp_dir / "cdp_browser.log"

    def start(self) -> None:
        from websockets.sync.client import connect  # 延迟导入，缺失时给出中文提示

        self.port = free_port()
        command = [
            self.browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={CAPTURE_WIDTH},{CAPTURE_HEIGHT}",
            f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={self.temp_dir / 'cdp_profile'}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "about:blank",
        ]
        log(f"[浏览器] 启动 CDP 无头浏览器：{' '.join(command)}")
        handle = self._log_path.open("w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            command, stdout=handle, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
        )
        version = None
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/version", timeout=2
                ) as response:
                    version = json.loads(response.read())
                break
            except Exception:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.5)
        if not version or not version.get("webSocketDebuggerUrl"):
            raise RuntimeError(
                "CDP 调试端口未就绪（/json/version 无响应）。日志尾部：\n" + tail_text(self._log_path)
            )
        self.browser_ws_url = version["webSocketDebuggerUrl"]
        log(f"[浏览器] CDP 就绪：{version.get('Browser', '未知')}，调试端口 {self.port}")
        with connect(self.browser_ws_url, open_timeout=10) as probe:
            probe.send(json.dumps({"id": 1, "method": "Browser.getVersion"}))
            probe.recv(timeout=10)

    @staticmethod
    def _call(ws, msg_id: int, method: str, params: dict | None = None,
              timeout: float = 30) -> dict:
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                raw = ws.recv(timeout=max(0.2, min(remaining, 2)))
            except Exception:  # 超时或无关事件，继续等待匹配 id 的响应
                continue
            message = json.loads(raw)
            if message.get("id") == msg_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} 返回错误：{message['error']}")
                return message.get("result", {})
        raise TimeoutError(f"CDP {method} 调用超时（{timeout} 秒）")

    def _wait_rendered(self, ws, page_name: str, msg_id: int,
                       max_wait: float = 45, min_wait: float = 3) -> tuple[bool, str]:
        """等待 Streamlit 通过 websocket 真正渲染出内容，并返回渲染后的 DOM 文本。"""
        start = time.time()
        last_len = -1
        stable = 0
        text = ""
        expression = (
            "(() => { const t = (document.body && document.body.innerText || '').trim();"
            " return JSON.stringify({n: t.length, t: t}); })()"
        )
        while time.time() - start < max_wait:
            try:
                result = self._call(
                    ws, msg_id, "Runtime.evaluate",
                    {"expression": expression, "returnByValue": True}, timeout=15,
                )
                payload = json.loads(result.get("result", {}).get("value", "{}"))
                length = int(payload.get("n", 0))
                text = str(payload.get("t", ""))
            except Exception:
                length = 0
                text = ""
            elapsed = time.time() - start
            if length > 80 and elapsed >= min_wait:
                stable = stable + 1 if length == last_len else 0
                if stable >= 3:
                    log(f"[渲染] {page_name} 已就绪（可见文本 {length} 字，耗时 {elapsed:.1f} 秒）")
                    return True, text
            else:
                stable = 0
            last_len = length
            time.sleep(0.6)
        log(f"[渲染] {page_name} 在 {max_wait:.0f} 秒内未检测到稳定的页面内容")
        return False, ""

    def capture(self, url: str, temp_png: Path, page_name: str) -> tuple[bool, str, str]:
        """返回 (是否成功, 错误原因, 渲染后的 DOM 文本)。"""
        from websockets.sync.client import connect

        if temp_png.exists():
            temp_png.unlink()
        # 每张图用一个全新的 about:blank 标签，避免复用标签时截到上一个页面的残留内容。
        encoded = urllib.parse.quote("about:blank", safe="")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?{encoded}", method="PUT"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                target = json.loads(response.read())
        except Exception as exc:
            return False, f"创建 CDP 页面标签失败：{exc}", ""
        target_id = target.get("id", "")
        try:
            with connect(target["webSocketDebuggerUrl"], open_timeout=15,
                         max_size=None) as ws:
                msg_id = 1
                self._call(ws, msg_id, "Page.enable"); msg_id += 1
                self._call(ws, msg_id, "Runtime.enable"); msg_id += 1
                self._call(ws, msg_id, "Emulation.setDeviceMetricsOverride",
                           {"width": CAPTURE_WIDTH, "height": CAPTURE_HEIGHT,
                            "deviceScaleFactor": 1, "mobile": False}); msg_id += 1
                self._call(ws, msg_id, "Page.bringToFront"); msg_id += 1
                self._call(ws, msg_id, "Page.navigate", {"url": url}); msg_id += 1
                rendered, text = self._wait_rendered(ws, page_name, msg_id)
                if not rendered:
                    return False, "页面在限定时间内未完成真实渲染（DOM 内容未稳定）", ""
                msg_id += 1
                shot = self._call(ws, msg_id, "Page.captureScreenshot",
                                  {"format": "png", "captureBeyondViewport": False}, timeout=45)
                data = shot.get("data")
                if not data:
                    return False, "Page.captureScreenshot 未返回图片数据", ""
                temp_png.write_bytes(base64.b64decode(data))
                return True, "", text
        except Exception as exc:
            return False, f"CDP 截图失败：{exc}", ""
        finally:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/close/{target_id}", timeout=5
                ).read()
            except Exception:
                pass

    def close(self) -> None:
        if self.browser_ws_url:
            try:
                from websockets.sync.client import connect
                with connect(self.browser_ws_url, open_timeout=8) as ws:
                    ws.send(json.dumps({"id": 999, "method": "Browser.close"}))
                log("[清理] 已向 CDP 浏览器发送 Browser.close。")
            except Exception as exc:
                log(f"[清理] Browser.close 未成功：{exc}")
        stop_process(self.proc, "无头浏览器")


def write_readme(results: list[dict], browser: str, backend_port: int,
                 frontend_port: int, captured_at: str, capture_method: str) -> None:
    successes = [item for item in results if item["ok"]]
    failures = [item for item in results if not item["ok"]]
    lines = [
        "# Streamlit 页面截图",
        "",
        "本目录中的 PNG 由 `scripts/capture_screenshots.py` 调用本机无头浏览器",
        "（Microsoft Edge / Google Chrome）**真实渲染**后截取，未使用任何占位图或伪造图片。",
        "渲染失败或页面未成功切换的截图不会保留。",
        "",
        "## 采集信息",
        "",
        f"- 截取时间：{captured_at}",
        f"- 浏览器：`{browser}`",
        f"- 本次独立启动的后端端口：`{backend_port}`（uvicorn，临时数据库）",
        f"- 本次独立启动的前端端口：`{frontend_port}`（streamlit）",
        f"- 截图窗口：`{CAPTURE_WIDTH}x{CAPTURE_HEIGHT}`",
        f"- 截图方式：{capture_method}",
        f"- 前端入口：`frontend/app.py`（`st.navigation()` 组织 5 个页面）",
        "",
        "## 已成功截取的页面",
        "",
    ]
    if successes:
        lines += [
            "| 文件 | 对应页面 | 访问路径 | 像素 | 文件大小 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in successes:
            w, h = item["size"]
            lines.append(
                f"| `{item['filename']}` | {item['page']} | `{item['url']}` | "
                f"{w}x{h} | {item['bytes']:,} 字节 |"
            )
    else:
        lines.append("（无：本次采集没有产生任何真实渲染成功的截图。）")
    lines += [
        "",
        "## 未截取到的页面及原因",
        "",
    ]
    if failures:
        lines += ["| 对应页面 | 访问路径 | 原因 |", "| --- | --- | --- |"]
        for item in failures:
            lines.append(f"| {item['page']} | `{item['url']}` | {item['reason']} |")
    else:
        lines.append("（无：5 个页面均成功截取。）")
    lines += [
        "",
        "> 说明：Streamlit `st.navigation()` 的页面 URL 由 `st.Page` 的文件名推断，",
        "> 默认页为 `/`。若某些 URL 渲染出的仍是默认页或空白页，脚本会判定为",
        "> 未真实截取并丢弃对应图片，具体原因见上表。",
        "",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")
    log(f"[说明] 已写出 {OUT_DIR / 'README.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="采集真实的 Streamlit 页面截图（中文提示）")
    parser.add_argument("--backend-port", type=int, default=8010, help="独立后端端口，默认 8010")
    parser.add_argument("--frontend-port", type=int, default=8510, help="独立前端端口，默认 8510")
    parser.add_argument("--budget", type=int, default=18000,
                        help="无头浏览器虚拟时间预算（毫秒），默认 18000")
    args = parser.parse_args()

    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("=" * 72)
    log("作品集截图采集脚本（仅新增 docs/screenshots/ 下的真实截图）")
    log(f"项目根目录：{ROOT}")
    log(f"开始时间：{captured_at}")
    log("=" * 72)

    browser = detect_browser()
    if browser is None:
        log("[失败] 浏览器不可用，未生成任何截图。")
        return 2

    temp_dir = Path(tempfile.mkdtemp(prefix="eka_capture_"))
    log(f"[临时] 本次运行临时目录：{temp_dir}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 清掉上一次运行留下的同名截图，保证目录里只保留本次真实渲染成功的图片。
    for stem, _, _ in PAGES:
        stale = OUT_DIR / f"{stem}.png"
        if stale.exists():
            stale.unlink()
            log(f"[清理] 移除上一次运行残留的截图：{stale.name}")

    backend_proc: subprocess.Popen | None = None
    frontend_proc: subprocess.Popen | None = None
    session: HeadlessSession | None = None
    capture_method = "CDP（Chrome DevTools Protocol，等待真实渲染完成后截图）"
    results: list[dict] = []
    backend_port = frontend_port = 0

    try:
        # 独立数据库 + 独立上传目录，避免与用户在 8000/8501 上已运行的服务共用数据。
        backend_env = os.environ.copy()
        backend_env["DB_PATH"] = str(temp_dir / "capture.db")
        backend_env["UPLOAD_DIR"] = str(temp_dir / "uploads")
        frontend_env = os.environ.copy()

        backend_port = pick_port(args.backend_port)
        frontend_port = pick_port(args.frontend_port)
        frontend_env["API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"

        backend_log = temp_dir / "backend.log"
        frontend_log = temp_dir / "frontend.log"

        backend_proc = spawn(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(backend_port), "--log-level", "warning"],
            backend_env, backend_log, "后端 uvicorn",
        )
        frontend_proc = spawn(
            [sys.executable, "-m", "streamlit", "run", "frontend/app.py",
             "--server.address", "127.0.0.1", "--server.port", str(frontend_port),
             "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            frontend_env, frontend_log, "前端 streamlit",
        )

        if not wait_health(f"http://127.0.0.1:{backend_port}/api/health", "后端",
                           backend_proc, backend_log):
            log("[失败] 后端未就绪，未生成任何截图。")
            return 3
        if not wait_health(f"http://127.0.0.1:{frontend_port}/_stcore/health", "前端",
                           frontend_proc, frontend_log):
            log("[失败] 前端 /_stcore/health 未就绪，未生成任何截图。")
            return 4

        base = f"http://127.0.0.1:{frontend_port}"
        # 多给一点时间，等待 Streamlit 完成首次脚本执行与页面注册。
        log("[等待] 额外等待 5 秒，让 Streamlit 完成首次脚本执行……")
        time.sleep(5)

        # 优先用 CDP：可在真实时间等待 Streamlit 的 websocket 渲染完成，
        # 避免命令行 --screenshot 截到空白加载骨架。CDP 不可用时回退到命令行。
        session = HeadlessSession(browser, temp_dir)
        try:
            session.start()
        except Exception as exc:
            log(f"[警告] CDP 模式不可用：{exc}")
            log("[警告] 回退到命令行 --screenshot 模式（对 Streamlit 渲染时序可能不稳定）。")
            session.close()
            session = None
            capture_method = "命令行 --screenshot（CDP 不可用时的兜底）"

        baseline_sample: list[int] | None = None
        baseline_text = ""
        for index, (stem, path, page_name) in enumerate(PAGES, start=1):
            url = base + path
            filename = f"{stem}.png"
            final_path = OUT_DIR / filename
            temp_png = temp_dir / f"capture_{index:02d}.png"
            profile_dir = temp_dir / f"profile_{index:02d}"
            log("-" * 72)
            log(f"[截图 {index}/{len(PAGES)}] {page_name} -> {url}")

            reachable = http_ok(url, timeout=5)
            if not reachable:
                reason = f"访问路径 `{path}` 返回非 200，Streamlit 未对该 URL 提供页面"
                log(f"[失败] {reason}。")
                if final_path.exists():
                    final_path.unlink()
                results.append({"filename": filename, "page": page_name, "url": path,
                                "ok": False, "reason": reason, "size": (0, 0), "bytes": 0})
                continue

            if session is not None:
                ok, error, rendered_text = session.capture(url, temp_png, page_name)
            else:
                ok, error, rendered_text = capture(browser, url, temp_png, profile_dir, args.budget, temp_dir)
            if not ok:
                log(f"[失败] {page_name}：{error}，不保留图片。")
                if final_path.exists():
                    final_path.unlink()
                results.append({"filename": filename, "page": page_name, "url": path,
                                "ok": False, "reason": error, "size": (0, 0), "bytes": 0})
                continue

            info = validate_png(temp_png)
            if baseline_sample is None:
                baseline_sample = info["sample"]
                baseline_text = rendered_text
            else:
                # CDP 模式下以 DOM 文本为准判断页面是否真的切换；
                # 命令行兜底模式拿不到 DOM 文本，才退回像素差判断。
                if rendered_text and baseline_text:
                    similarity = difflib.SequenceMatcher(
                        None, baseline_text, rendered_text
                    ).ratio()
                    diff = mean_abs_diff(baseline_sample, info["sample"])
                    log(f"[校验] 与默认页 DOM 文本相似度 {similarity:.3f}，平均像素差 {diff:.2f}")
                    if similarity > 0.97:
                        reason = (f"该 URL 渲染出的 DOM 文本与默认页几乎相同（相似度 {similarity:.3f}），"
                                  "说明 st.navigation 未切换到目标页面，按未真实截取处理")
                        log(f"[失败] {page_name}：{reason}，不保留图片。")
                        if final_path.exists():
                            final_path.unlink()
                        results.append({"filename": filename, "page": page_name, "url": path,
                                        "ok": False, "reason": reason, "size": (0, 0), "bytes": 0})
                        continue
                else:
                    diff = mean_abs_diff(baseline_sample, info["sample"])
                    log(f"[校验] 与默认页的平均像素差：{diff:.2f}（兜底模式）")
                    if diff < 1.0:
                        reason = (f"该 URL 渲染结果与默认页几乎相同（平均像素差 {diff:.2f}），"
                                  "说明 st.navigation 未切换到目标页面，按未真实截取处理")
                        log(f"[失败] {page_name}：{reason}，不保留图片。")
                        if final_path.exists():
                            final_path.unlink()
                        results.append({"filename": filename, "page": page_name, "url": path,
                                        "ok": False, "reason": reason, "size": (0, 0), "bytes": 0})
                        continue

            shutil.copyfile(temp_png, final_path)
            log(f"[完成] {page_name} -> {final_path.name}（{info['bytes']:,} 字节）")
            results.append({"filename": filename, "page": page_name, "url": path,
                            "ok": True, "reason": "", "size": info["size"], "bytes": info["bytes"]})

        log("=" * 72)
        success_count = sum(1 for item in results if item["ok"])
        log(f"[汇总] 真实渲染成功 {success_count}/{len(PAGES)} 张；失败 {len(PAGES) - success_count} 张。")
        for item in results:
            mark = "成功" if item["ok"] else "失败"
            log(f"        [{mark}] {item['page']:<16s} {item['filename']:<22s} {item['reason']}")
        write_readme(results, browser, backend_port, frontend_port, captured_at, capture_method)
        log("=" * 72)
        return 0 if success_count else 5
    finally:
        if session is not None:
            session.close()
        stop_process(frontend_proc, "前端 streamlit")
        stop_process(backend_proc, "后端 uvicorn")
        shutil.rmtree(temp_dir, ignore_errors=True)
        log(f"[清理] 临时目录已删除：{temp_dir}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("[中断] 用户按下 Ctrl+C，未生成任何伪造截图。")
        sys.exit(130)
