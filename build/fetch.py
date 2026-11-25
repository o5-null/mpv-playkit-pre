"""下载组件并做 SHA-256 二次校验。

缓存按 sha256 定位到 `<缓存根>/_sha256/<哈希>/<文件名>`：本地统一工作区里缓存根是
`repos/.cache/downloads`（多仓库共用），否则是仓库内 `.work/downloads`。命中且哈希一致
时直接复用；共享产物目录 `repos/dist` 里有同名且哈希一致的归档时也会先硬链接复用，
不再下载。支持 HTTP_PROXY / HTTPS_PROXY 环境变量（urllib 默认读取）。
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                declared = resp.headers.get("Content-Length")
                with part.open("wb") as out:
                    total = 0
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        total += len(chunk)
            if part.stat().st_size == 0:
                raise IOError("下载内容为空")
            # 连接提前关闭时 urllib 不报错，只能靠 Content-Length 兜底
            if declared and declared.isdigit() and int(declared) != total:
                raise IOError(f"下载不完整: {total}/{declared} 字节")
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


def local_override(comp: dict) -> Path | None:
    """调试/未发布时的本地资产覆盖。

    PLAYKIT_LOCAL_<ID>（id 大写，"/"→"__"、"-"→"_"）指向本地文件即可跳过下载与哈希；
    mpv 另支援旧名 PLAYKIT_MPV_ARCHIVE，方便直接指向自己刚编出来的 zip。
    覆盖会用实际文件参与装配，BUILD_INFO 里会记真实 sha256 并标出被覆盖的锁值。
    """
    keys = []
    if comp.get("id") == "mpv":
        keys.append("PLAYKIT_MPV_ARCHIVE")
    keys.append("PLAYKIT_LOCAL_" + comp["id"].upper().replace("/", "__").replace("-", "_"))
    for key in keys:
        value = os.environ.get(key)
        if value:
            path = Path(value).expanduser()
            if not path.is_file():
                common.fail(f"{key} 指向的文件不存在: {path}")
            return path
    return None


def _shared_asset(comp: dict) -> Path | None:
    """共享产物目录（repos/dist）里已有同名且哈希一致的归档时直接复用。

    典型情形：某个合并 zip 刚作为 release 资产复制进共享 dist，构建不必再下几百 MB；
    哈希不符（同名不同版）就当没命中，照常走下载。
    """
    dist = common.SHARED_DIST_DIR
    if dist is None:
        return None
    candidate = dist / asset_filename(comp)
    if not candidate.is_file():
        return None
    if common.sha256_file(candidate) != comp["sha256"].strip().lower():
        return None
    return candidate


def fetch(comp: dict, force: bool = False) -> Path:
    """返回本地缓存路径，保证 SHA-256 与清单一致。"""
    local = local_override(comp)
    if local is not None:
        common.log(f"本地覆盖 {comp['id']}: {local.name}（跳过下载与哈希校验）")
        return local
    # 缓存按 sha256 定位：多个组件指向同一资产（比如四个引擎共用 vs-framegen 的合并 zip）
    # 时只存一份、只下一次，而不是每个 id 目录各存一份 253 MB 的副本。
    expected = comp["sha256"].strip().lower()
    dest = common.DOWNLOAD_DIR / "_sha256" / expected / asset_filename(comp)
    if dest.exists() and not force:
        actual = common.sha256_file(dest)
        if actual == expected:
            common.log(f"缓存命中 {comp['id']}: {dest.name}")
            return dest
        common.log(f"缓存哈希不匹配，重新下载 {comp['id']}")
        dest.unlink()
    shared = _shared_asset(comp) if not force else None
    if shared is not None:
        # 同卷硬链接即可，避免再复制一份；跨卷或不支持时退回复制
        dest.parent.mkdir(parents=True, exist_ok=True)
        common.log(f"复用共享产物 {comp['id']}: {shared}")
        try:
            os.link(shared, dest)
        except OSError:
            shutil.copy2(shared, dest)
        return dest
    _download(comp["url"], dest)
    actual = common.sha256_file(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        common.fail(f"组件 {comp['id']} 校验失败\n  期望 {expected}\n  实际 {actual}")
    return dest


def fetch_all(selected: list[dict], force: bool = False) -> dict[str, Path | None]:
    """按需下载；仓库内文件（repo-files）没有 url，值为 None。"""
    result: dict[str, Path | None] = {}
    for comp in selected:
        if not comp.get("url"):
            result[comp["id"]] = None
            continue
        result[comp["id"]] = fetch(comp, force=force)
    return result
