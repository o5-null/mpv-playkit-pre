"""下载组件并做 SHA-256 二次校验。

缓存位于 .work/downloads/<id>/<文件名>，命中且哈希一致时直接复用。
支持 HTTP_PROXY / HTTPS_PROXY 环境变量（urllib 默认读取）。
个别站点（如 codeload）经代理会握手失败，此时回退到 curl 重试一次。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import common

USER_AGENT = "mpv-playkit-pre-build/1.0"
CHUNK = 1 << 20


def _proxy() -> str:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _download_curl(url: str, dest: Path, timeout: int) -> None:
    """urllib 走代理握手失败时的回退；curl 对这类站点更稳。"""
    curl = shutil.which("curl")
    if not curl:
        common.fail("需要 curl 作为下载回退，但 PATH 中没有 curl")
    part = dest.with_suffix(dest.suffix + ".part")
    cmd = [curl, "-L", "-f", "-s", "-S", "--connect-timeout", "30",
           "--max-time", str(timeout)]
    proxy = _proxy()
    if proxy:
        cmd += ["-x", proxy]
    cmd += ["-o", str(part), url]
    common.log(f"回退 curl 下载: {url}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not part.exists() or part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        detail = (proc.stderr or "").strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
        common.fail(f"curl 下载失败: {url}\n{detail[0]}")
    part.replace(dest)


def asset_filename(comp_or_url: dict | str) -> str:
    """从组件字典或裸 url 推导文件名（pin 工具只有 url）。

    codeload 的仓库 tarball 末段是 commit sha，没有扩展名，补成 .tar.gz。
    """
    url = comp_or_url["url"] if isinstance(comp_or_url, dict) else str(comp_or_url)
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path)
    if not name:
        common.fail(f"无法从 url 解析文件名: {url}")
    name = urllib.parse.unquote(name)
    if len(name) == 40 and all(ch in "0123456789abcdef" for ch in name.lower()):
        name += ".tar.gz"
    return name


def _download(url: str, dest: Path, timeout: int = 300, retries: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            common.log(f"下载 ({attempt}/{retries}): {url}")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, part.open("wb") as out:
                total = 0
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    total += len(chunk)
            if part.stat().st_size == 0:
                raise IOError("下载内容为空")
            part.replace(dest)
            common.log(f"完成 {dest.name} ({total} 字节)")
            return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:  # 网络错误统一重试
            last_error = exc
            part.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(2 * attempt)
    if last_error is not None and _proxy():
        _download_curl(url, dest, timeout)
        common.log(f"完成 {dest.name} ({dest.stat().st_size} 字节)")
        return
    common.fail(f"下载失败: {url}\n{last_error}")


def fetch(comp: dict, force: bool = False) -> Path:
    """返回本地缓存路径，保证 SHA-256 与清单一致。"""
    dest = common.DOWNLOAD_DIR / comp["id"] / asset_filename(comp)
    expected = comp["sha256"].strip().lower()
    if dest.exists() and not force:
        actual = common.sha256_file(dest)
        if actual == expected:
            common.log(f"缓存命中 {comp['id']}: {dest.name}")
            return dest
        common.log(f"缓存哈希不匹配，重新下载 {comp['id']}")
        dest.unlink()
    _download(comp["url"], dest)
    actual = common.sha256_file(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        common.fail(f"组件 {comp['id']} 校验失败\n  期望 {expected}\n  实际 {actual}")
    return dest


def fetch_all(selected: list[dict], force: bool = False) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for comp in selected:
        result[comp["id"]] = fetch(comp, force=force)
    return result
