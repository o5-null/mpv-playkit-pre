"""构建系统包。

分层（参照 100pangci/mpv_PlayKit_TLS）：
    manifests/components.yml  组件规则（怎么装）
    sources.lock.json         组件 pin（装哪个版本）
    build/inputs.py           构建输入指纹（产物可追溯）
    build/fetch.py            下载 + SHA-256 校验
    build/assemble.py         装配 stage
    build/smoke.py            运行时冒烟测试
    build/package.py          确定性 zip
    build/verify.py           stage / 归档结构校验
    build/sync.py             同步上游 hooke007/mpv_PlayKit
    build/pin.py              写 sources.lock.json
"""

__all__ = [
    "assemble",
    "common",
    "fetch",
    "inputs",
    "package",
    "pin",
    "smoke",
    "sync",
    "verify",
]
