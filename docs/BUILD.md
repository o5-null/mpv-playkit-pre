# 构建链

## 为什么不 fork 上游就完事

[hooke007/mpv_PlayKit](https://github.com/hooke007/mpv_PlayKit) 是**配置仓库**：没有 CI、
没有构建脚本、不产出 mpv 可执行文件。它的官方包 `mpv-lazy-<日期>.7z` 是仓库主手工拼的，
且明确不支持自更新。

所以本仓库的做法是：**把"配置"当上游同步，把"打包"当自己的活**。
mpv 用 [shinchiro](https://github.com/shinchiro/mpv-winbuild-cmake) 的官方 Windows 构建，
Python 与 VapourSynth 运行时用各自的官方件（python.org embed zip + PyPI wheel），
K7sfunc 用自维护 fork 的源码树——全部按 SHA-256 钉住。

## 不变量（改代码前先读这几条）

1. **不在上游目录里写东西。** `portable_config/`、`installer/` 只由 `build sync` 整目录替换。
   自定义功能一律进 K7sfunc fork，本仓库不往这两个目录里加文件。
2. **二进制不入库。** 所有第三方资产在构建时下载，用 `sources.lock.json` 里的 sha256 校验。
3. **规则与版本分离。** 换版本只改 `sources.lock.json`（由 `build.pin` 写入），
   `manifests/components.yml` 里没有版本号。
4. **不手改 lock。** 要让某个组件上线，先跑完整构建（含 smoke）再提交 lock，
   这样 lock 永远代表"验证过的组合"。
5. **产物必须可追溯。** `BUILD_INFO.json` 里有 `source_commit`、`inputs_hash`、
   `lock_digest` 与每个组件的 url/sha256/size。

## 目录职责

```
manifests/components.yml   组件规则（kind / 装到哪 / exclude / license）
manifests/packs/*.yml      拓展包清单（overlay zip 的组件，版本同样是 lock 的 <pack>/<id>）
sources.lock.json          组件 pin（version / url / sha256 / size）
build/common.py            路径、校验、解包、进程、版本号
build/inputs.py            构建输入哈希（BUILD_INFO.inputs_hash）
build/fetch.py             下载 + 哈希校验，缓存 .work/downloads/<id>/（codeload 走 curl 回退）
build/assemble.py          装配 stage（组件 -> portable_config -> licenses）
build/smoke.py             python imports / mpv --version / vf=vapoursynth
build/package.py           确定性 zip + .sha256（flat=True 时不带顶层目录，给补丁包用）
build/pack.py              装配并打包拓展包（overlay zip）
build/verify.py            stage 与 zip 的结构、禁止项、BUILD_INFO 校验
build/sync.py              同步上游两个目录 + 写 upstream.json
build/pin.py               下载新资产、算哈希、写 lock（--pack 走补丁包命名空间）
```

## 一次完整构建做了什么

```text
python -m build ci          # = fetch + 下面这一串；本地复现 CI 用这个
python -m build all         # = 跳过 fetch，其余同上
```

```
python -m build all
  ├─ assemble(version)
  │    ├─ select_components()        规则 + lock 合并，处理 --with/--without
  │    ├─ fetch.fetch_all()          缓存命中则只验哈希
  │    ├─ INSTALLERS[kind]            mpv-7z / archive / whl / file / git-tree
  │    ├─ copy_configuration()       上游 portable_config（overlay/ 存在时再叠加）
  │    ├─ copy_licenses()            licenses/THIRD_PARTY.md
  │    ├─ write_build_info()         BUILD_INFO.json（含 inputs_hash / lock_digest）
  │    └─ verify_stage_minimum()     必需项检查（支持 glob）
  ├─ smoke(stage)                    python 侧 import + mpv 侧 lavfi 恒等 vpy
  ├─ package.zip_stage()             确定性 zip（固定 mtime、固定权限位）
  ├─ verify.check_stage()            禁止项：__pycache__ / .pyc / sdk / 7z.exe ...
  └─ verify.check_archive()          根目录唯一、必需文件、禁止目录
```

版本号来自 `VERSION` + 提交短哈希（`2026.11.20-9d5954a`），可用 `--version` 覆盖；
CI 里用 `PLAYKIT_VERSION`。

## 可复现性

- 归档内所有条目 `date_time` 固定为 `2020-01-01 00:00:00`（`common.FIXED_TIME`）；
- 目录条目用 STORE、文件用 deflate 6；`.exe/.com/.bat` 置 0755，其余 0644；
- `inputs_hash` 对 `build/ manifests/ sources.lock.json upstream.json
  VERSION requirements.txt .github/workflows/build.yml` 逐文件求哈希后排序再哈希，
  与遍历顺序、机器、时间无关；
- 同一份 `inputs_hash` + 同一份 lock 应当产出同一个 zip（`built_at` 字段除外）。

`portable_config/` 不进 inputs_hash：它 132MB 且由上游同步而来，身份由
`upstream.json` 的 commit id 表示，而 `upstream.json` 本身在哈希范围内。

## 换版本

**mpv（最常见）**

```bash
# 1) 找新 tag 与资产名
gh release list -R shinchiro/mpv-winbuild-cmake --limit 3
# 2) 钉住（下载 + 算哈希 + 写 lock）
python -m build.pin --id mpv \
  --url https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261201/mpv-x86_64-20261201-git-xxxxxxx.7z
# 3) 完整验证
python -m build all
```

`--version` 不给时用文件名主干做版本标签，想更整洁就显式传。

**换 Python / VapourSynth**：两个独立组件，各自钉新版。

```bash
# 官方嵌入式 Python（python.org 的 embed zip）
python -m build.pin --id python --version 3.15.3 \
  --url https://www.python.org/ftp/python/3.15.3/python-3.15.3-embed-amd64.zip
# 官方 VapourSynth（PyPI wheel，cp312-abi3 稳定 ABI）
python -m build.pin --id vapoursynth --version R83 \
  --url https://files.pythonhosted.org/packages/.../vapoursynth-83-cp312-abi3-win_amd64.whl
```

升级后要确认三件事：wheel 里仍有 `vsscript.dll`、`libvapoursynth.dll`、`libvapoursynthfilters*.dll`（manifest 的 `copies` 依赖这些名字）；
`python3xx._pth` 仍存在（`python_pth` 后处理依赖它）；`vsscript.dll` 的 Python 定位方式没变（R82 起是"四层上溯 → TOML"，
细节见 `docs/DECISIONS.md` 第 2 条）。缺一项 `verify_stage_minimum` 或冒烟测试会当场拦住。

**换 yt-dlp**：`kind: file` 组件，钉官方 release 的 `yt-dlp.exe`：

```bash
python -m build.pin --id yt-dlp --version 2026.10.26 \
  --url https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.26/yt-dlp.exe
```

**换 K7sfunc（fork）**：先 push 到 fork，再钉新的 commit：

```bash
python -m build.pin --id k7sfunc --version 1.9.0+pre.3 \
  --url https://codeload.github.com/o5-null/K7sfunc/tar.gz/<40位commit>
```

`git-tree` 组件解包后按 `paths` 逐项复制（`src/k7sfunc` 进 `Lib/site-packages/`，
两个前端文件进 `portable_config/`），所以 fork 里新增别的文件不会自动进包——
要加东西就改规则里的 `paths`。`k7sfunc.__version__` 会进冒烟测试日志，能直接看出装了哪版。

**加一个组件**：在 `manifests/components.yml` 里加一条规则（`kind` 选
`mpv-7z/archive/whl/file/git-tree`），然后 `build.pin` 写 lock。若需要新的安装方式，
在 `build/assemble.py` 的 `INSTALLERS` 里加函数。

## 拓展包（overlay zip）

拓展包是叠加到基础包根目录的补丁包，**不带顶层目录**，解压即覆盖。清单在
`manifests/packs/<name>.yml`，组件规则与基础包同一套 `kind`，版本仍写 `sources.lock.json`，
键是 `<pack>/<id>`：

```
python -m build.pin --pack framegen --id vs-framegen --url <url>   # 钉版本
python -m build pack --name framegen                               # 只打一个
python -m build pack                                               # 打全部
python -m build verify --pack --asset dist/out/<pack>.zip          # 校验产物
```

内容白名单（`build/pack.py: FORBIDDEN_REL` / `verify.check_pack_archive`）：

```
Lib/site-packages/vapoursynth/plugins/**   插件 DLL，VapourSynth 启动时自动加载（含子目录）
Lib/site-packages/<其它>/**                补丁包自己的 Python 运行依赖（onnx/numpy 等）
vs-plugins/**                              引擎包、许可、第三方说明等资源
portable_config/**                         与基础包不同的配置（解压时直接覆盖）
PACK_INFO.json                             包名、组件清单、lock_digest
```

`Lib/site-packages/` 下**除了 `vapoursynth/` 本体**都可以放——补丁包常需要自己的 Python 依赖
（例如 TRT-RTX 建引擎要 `onnx`），基础包的 embed Python 没有 pip，只能随包落进 site-packages。

补丁包**可以**覆盖 `portable_config/` 下的配置——如果需要不同的.conf/脚本，直接放进补丁包，
解压即生效。但**不得**包含基础包的运行时本体（`mpv.exe`、`python.exe`、`vsscript.dll`、
`Lib/site-packages/vapoursynth/vapoursynth.pyd`、`k7sfunc/` 等），因为覆盖式解压写错就毁基础包。
另一个易错点是 wheel 里的 `*.dist-info/` 目录条目——`exclude` 要同时写 `"*.dist-info"` 和
`"*.dist-info/*"`。但**补丁包自己的 Python 依赖要留着 `*.dist-info`**：包是拿元数据读版本号的，
删掉后 `onnx.__version__` 会变成 `'unknown'`，`onnxconverter_common` 一调 `packaging.Version()`
就抛 `InvalidVersion`。

**加一个拓展包**：写 `manifests/packs/<name>.yml`（`schema: 1`、`name`、`title`、
`summary`、`components`），每个组件建议写 `provides`（产物里应出现的相对路径），
`pack.py` 会逐条校验；然后 `pin --pack` 写 lock。

## CI

`.github/workflows/build.yml`：push main / PR / 手动触发 → 构建 → 上传 artifact
（14 天）。**故意不发布 release、不推 tag**，产物只走 artifact。CI 会先上传基础包
（`mpv-playkit-pre-windows-x64`），再打并上传拓展包（`mpv-playkit-pre-packs-windows-x64`，
只含 `dist/out/*-pack-*.zip`）。

`.github/workflows/sync-upstream.yml`：每天 UTC 03:00 跑 `python -m build sync`
（退出码 3 = 上游无更新），有变化就用 bot 身份提交 `chore: 同步上游 hooke007/mpv_PlayKit`。

缓存策略：`actions/cache` 存 `.work/downloads`，key 用 `sources.lock.json` 的哈希——
lock 一变缓存就失效，避免拿到旧资产。

## 失败排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Error parsing option vf` | 滤镜参数用 `:` 分隔，Windows 路径里的盘符冒号被误解析 | 用相对路径（smoke 就是这么做的）或 `--vf=vapoursynth="路径"` |
| `sources.lock.json 缺少组件` | 加了规则没钉版本 | `python -m build.pin --id <id> --url <url>` |
| `stage 含禁止目录: __pycache__` | 有代码在 stage 里跑了 Python 且没禁字节码 | 用 `PYTHONDONTWRITEBYTECODE=1`；smoke 已内置 |
| 下载反复重试后失败 | 代理/网络；GitHub 资产会 302 到 `release-assets.githubusercontent.com` | 确认 `HTTPS_PROXY` 生效（urllib 直接读环境变量） |
| `找不到 7z 或 bsdtar` | 本机没有 7z | Windows 10+ 自带 `tar.exe` 可解 7z；否则装 7-Zip 或设 `SEVEN_Z` |
