# 构建链

## 为什么不 fork 上游就完事

[hooke007/mpv_PlayKit](https://github.com/hooke007/mpv_PlayKit) 是**配置仓库**：没有 CI、
没有构建脚本、不产出 mpv 可执行文件。它的官方包 `mpv-lazy-<日期>.7z` 是仓库主手工拼的，
且明确不支持自更新。

所以本仓库的做法是：**把"配置"当上游同步，把"打包"当自己的活**。
mpv 用**我们自行维护的构建**：源码是 [o5-null/mpv](https://github.com/o5-null/mpv) 的 fork
（带 `vf_playkit` 帧倍增滤镜），产物是该仓库 release 上的平铺 zip（`mpv.exe` / `mpv.com`
加 MSYS2 CLANG64 的动态依赖闭包），打包脚本与 CI 在 `mpv-src/scripts/package_windows.py`
与 `mpv-src/.github/workflows/playkit-windows.yml`。
Python 与 VapourSynth 运行时用各自的官方件（python.org embed zip + PyPI wheel），
K7sfunc 用自维护 fork 的源码树——全部按 SHA-256 钉住。

## 不变量（改代码前先读这几条）

1. **`portable_config/` 是本地维护的基准配置。** 基准取自 mpv-lazy 最后发版的 `portable_config`，
   只有 `portable_config/shaders/` 仍由 `build sync` 整目录跟随上游（`installer/` 已冻结）。
   档位之间的配置差异一律写进 `manifests/config.yml`，由 `build/config.py` 生成，不手写副本。
   算法/前端功能进 K7sfunc fork，本仓库只按 commit 钉它。
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
manifests/packs/*.yml      拓展包清单（补丁归档的组件，版本同样是 lock 的 <pack>/<id>）
manifests/config.yml       配置清单：VF 预设表 + 每个档位包启用哪几个预设
sources.lock.json          组件 pin（version / url / sha256 / size）
build/common.py            路径、校验、解包、进程、版本号
build/inputs.py            构建输入哈希（BUILD_INFO.inputs_hash）
build/fetch.py             下载 + 哈希校验，缓存 <缓存根>/_sha256/<哈希>/（codeload 走 curl 回退）
build/assemble.py          装配 stage（组件 -> 配置清单生成 portable_config -> licenses）
build/config.py            按 manifests/config.yml 生成预设区、裁掉未启用的 vpy
portable_config/           本地维护的基准配置（mpv-lazy 最后发版；仅 shaders/ 跟随上游）
build/smoke.py             python imports / mpv --version / vf=vapoursynth
build/package.py           出包 + .sha256：默认 7z（-mx=7），--format zip 出确定性 zip
build/sevenzip.py          7z 定位、创建、列名、读成员（verify 复用）
build/pack.py              装配并打包拓展包（补丁归档）
build/verify.py            stage 与 zip 的结构、禁止项、BUILD_INFO 校验
build/sync.py              同步上游着色器目录 + 写 upstream.json
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
  │    ├─ copy_configuration()       基准 portable_config + 按 pack 生成预设区、裁 vpy
  │    ├─ copy_licenses()            licenses/THIRD_PARTY.md
  │    ├─ write_build_info()         BUILD_INFO.json（含 inputs_hash / lock_digest）
  │    └─ verify_stage_minimum()     必需项检查（支持 glob）
  ├─ smoke(stage)                    python 侧 import + mpv 侧 lavfi 恒等 vpy
  ├─ package.package_stage()         默认 7z（LZMA2 -mx=7），--format zip 时确定性 zip
  ├─ verify.check_stage()            禁止项：__pycache__ / .pyc / sdk / 7z.exe ...
  └─ verify.check_archive()          根目录唯一、必需文件、禁止目录
```

版本号来自 `VERSION` + 提交短哈希（`2026.11.20-9d5954a`），可用 `--version` 覆盖；
CI 里用 `PLAYKIT_VERSION`。

## 出包格式

默认出 `.7z`（LZMA2、`-mx=7`，体积约为 zip 的一半），体积比九档大约多 3~5%，
但打包耗时降到三分之一左右；
要 7-Zip 才能在用户侧解压，构建机需要 `7z.exe`——查找顺序 `PLAYKIT_7Z` 环境变量 →
`PATH` → 注册表 `SOFTWARE\7-Zip` → `C:\Program Files\7-Zip`（本机实测 winget 装在
`C:\software\7-Zip`，注册表里已登记）。`python -m build ... --format zip` 回退到旧行为。
`<产物目录>/<name>.sha256` 两种格式都有（产物目录默认是共享的 `repos/dist`，见下文"目录约定"）。

## 目录约定（本地共享产物）

本地各子仓库都在 `E:\code\dlssg-vfi\` 根下，构建缓存与交付归档统一放进根下的 `repos\`：

| 常量 | 有共享根时 | 无共享根时（CI、单独拷走） |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `repos\.cache\downloads` | `<repo>\.work\downloads` |
| `OUT_DIR` | `repos\dist` | `<repo>\dist\out` |
| `STAGE_ROOT` | `<repo>\dist\stage`（始终留在仓库内，单包 0.6–1.7 GB） | 同左 |

共享根判定在 `build/common.py::_shared_root()`：`PLAYKIT_SHARED_ROOT` 显式指定优先；
否则父目录下存在 `repos\dist` 或 `repos\.cache` 就用它（也兼容 `<root>\repos\<repo>` 的旧布局）。
下载顺序是「缓存命中 → `repos/dist` 里同名且 sha256 一致的归档（硬链接进缓存）→ 真正下载」，
所以刚作为 release 资产发出去的 zip 不必再下一次。CI 不设这两个变量，行为与加这条约定之前完全一致。

### 打包后 stage 一律保留（手动测试用）

`ci` / `all` / `pack` 都不会删除 stage：打包只是从 stage 读文件，结束后目录原样留着，
可以直接跑 `dist\stage\<包名>\mpv.exe` 验证，不必先解 7z。档位包的 stage
（`-vsdlssg` / `-vs-aji`）已经叠好本档组件，最接近用户拿到的包。

- 同名重建会先删掉旧 stage 再重装（`build/pack.py:176`、`build/assemble.py:356`）；
- 提交哈希变了目录名就变了，旧 stage 会一直堆着（单个 0.6–1.7 GB），
  需要空间时手工删 `dist\stage\<旧包名>`；`dist\out` 里的历史归档同理。

## 可复现性

- 默认 7z：`-mx=7 -m0=lzma2 -ms=on`（字典与匹配参数由档位自身决定，不再手写
  `-md=128m -mfb=273`，否则等于把九档参数套回七档），并 `-mtc=off -mtm=off -mta=off` 关掉时间戳，
  条目顺序取文件系统遍历，因此字节级可复现性不如 zip 严格；验体积与内容仍用 `verify --pack`；
- `--format zip` 时保留确定性路径：所有条目 `date_time` 固定为 `2020-01-01 00:00:00`（`common.FIXED_TIME`）、
  目录 STORE、文件 deflate 6、`.exe/.com/.bat` 置 0755 其余 0644；
- `inputs_hash` 对 `build/ manifests/ sources.lock.json configs/ upstream.json VERSION
  requirements.txt .github/workflows/build.yml` 以及 `portable_config/` 下的配置文本
  （`mpv.conf`、`input_uosc.conf`、`menu.conf`、`profiles.conf`、`script-opts.conf`、
  `scripts/`、`vs/`）逐文件求哈希后排序再哈希，与遍历顺序、机器、时间无关；
- 同一份 `inputs_hash` + 同一份 lock + 同一格式，应当产出同一份内容（`built_at` 字段、7z 头部字节除外）。

`portable_config/shaders/`（142MB）与 `fonts/`（14MB）不进 inputs_hash：前者身份由
`upstream.json` 的 commit id 表示（`upstream.json` 本身在哈希范围内），后者是静态资源。
配置文本必须进哈希——它现在是本地维护、直接决定包内容的东西。

## 配置清单（manifests/config.yml）

基准 `portable_config/` 是"全量预设"版本（mpv-lazy 最后发版的配置），
`manifests/config.yml` 决定每个档位包在它之上留哪些、禁哪些：

```yaml
schema: 1
presets:
  - id: dlssg            # 清单内唯一
    key: "*"             # input_uosc.conf 的按键
    vpy: vs/MEMC_DLSSG_NV.vpy
    label: 预设 补帧 Dlss (DLC-vsNV)   # input 的 #! 提示与 menu 的条目名
    requires: vsdlssg 引擎 vdlssg       # 写进"本包未启用"的说明
packs:
  base:                      # 中间基础 stage 的配置（不带 --pack 时用）
    enable: [mvt_lq]
  vsdlssg:
    enable: [mvt_lq, dlssg, xessfg, vfg, fsr4]
  vs-aji:
    enable: [mvt_lq, dlssg, xessfg, vfg, fsr4, aji_rife, aji_upscale, aji_tfix, aji_stack]
```

`build/config.py` 对 stage 做三件事：

1. 用 `presets` 的顺序重写 `input_uosc.conf` 与 `menu.conf` 里
   `# >>> playkit-config:vf` … `# <<< playkit-config:vf` 之间的内容；
   启用的行是可用键位，未启用的行整行加 `#` 并在行尾/标签后注明缺哪个组件。
2. 删掉 `vs/` 里未启用的 `.vpy`（真正的裁剪；清单外的 vpy 会报错）。
3. 保留文件原有行尾（这两份是 CRLF），再自检标记区、启用集合与 `vs/` 是否一致。

改完之后直接对已有 stage 重算，不需要重新下载：

```bash
python -m build config --stage dist/stage/<...> --pack vsdlssg
python -m build verify --stage dist/stage/<...> --pack vsdlssg
```

全量档位包（`pack --name vsdlssg`）里，基础包先按本档包名装配一次，组件装完后再按包名
重算一次——所以 `k7sfunc` 组件带来的引擎 vpy 不会被基础 stage 的 `base` 配置裁掉。
基础 stage（`build assemble` / `all`，不带 `--pack`）按 `base` 生成，只含 mpv + k7sfunc
基础依赖就能跑的预设（当前只有 `mvt_lq`）；`base` 不是交付物，用户拿到的是两个档位包。

## 换版本

**mpv（最常见）**

mpv 是我们自己的构建，换版本 = 换 `mpv-src` 的 tag/提交，重新出包：

```bash
# 1) 首选：推 tag，让 playkit-windows.yml 在 CI 里编译、出包并发 release
git tag -a playkit-20261001 -m "playkit build 20261001" && git push fork playkit-20261001
# 备用：本地编好后自己出包（CI 不可用时）
pwsh scripts\package_windows.py --out .\mpv-x86_64-playkit-20261001.zip --version 20261001
gh release create playkit-20261001 .\mpv-x86_64-playkit-20261001.zip -R o5-null/mpv
# 2) 两条路产出的资产名一致：mpv-x86_64-playkit-<版本>.zip
# 3) 钉住（资产已上传就让它自己下；还没上传就加 --file 用本地产物算哈希）
python -m build.pin --id mpv --version 20261001 \
  --url https://github.com/o5-null/mpv/releases/download/playkit-20261001/mpv-x86_64-playkit-20261001.zip
# 4) 完整验证
python -m build all
```

mpv 的 zip 只带 mpv.exe / mpv.com / 动态依赖闭包，**不含 VapourSynth 运行库**：`vf vapoursynth`
在运行时才去加载 `vsscript.dll`，这些文件由包里 `vapoursynth` 组件（whl）复制到包根，所以单独解压
mpv zip 只能看 `--vf=help` 里的条目，真要跑 `.vpy` 得放进 playkit 包里用。

本地试自己的构建时可以完全不碰 lock：`PLAYKIT_MPV_ARCHIVE=E:\...\mpv-x86_64-playkit-xxx.zip`
（或通用名 `PLAYKIT_LOCAL_<组件ID>`）会让 `fetch` 跳过下载与哈希；`BUILD_INFO.json` 里会记
真实 sha256 并标记 `overridden`，锁里的值留在 `sha256_locked`。

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

## 档位包（full / 补丁两种形态）

档位包的清单在 `manifests/packs/<name>.yml`，组件规则与基础包同一套 `kind`，版本仍写
`sources.lock.json`，键是 `<pack>/<id>`：

```
python -m build.pin --pack vsdlssg --id engine-framegen --url <url>  # 钉版本
python -m build pack --name vsdlssg                               # 只打一个
python -m build pack                                              # 打全部（默认并行）
python -m build pack --jobs 1                                     # 串行，便于看单包日志
python -m build verify --pack --asset ..\dist\<pack>.7z           # 校验产物（7z 或 zip 都收）
```

多个档位包默认**并行**（`--jobs`，缺省取 `min(包数, 4)`）：每个包在独立子进程里走
`assemble → config → 压缩 → 校验`，父进程按 `[包名]` 前缀转发日志。串行时三件套要
15~20 分钟，几乎全花在两件事上——每个包都从零复制 615 MB 基础树再叠组件，以及
`7z -mx=7` 的固实压缩；这两步互不独占同一份输入，所以并行能真正重叠。
组件下载/解压仍先**串行**预取（各档位共用基础包组件，同时解同一份缓存会互相踩）；
`fetch` 的缓存目录按 **sha256** 命名（`downloads/_sha256/<hash>/<文件名>`），多个组件指向
同一资产时只下一份、只存一份。
预取完才开始并行装配。单包失败会等其余包跑完后汇总，一次性报出失败包名。

清单里 `full: true` 时产出**全量包**：先把基础包装进同一个 stage，再叠本档组件，
产物与基础包同构（唯一顶层目录，`...-windows-x64-<name>.7z`），用户只下一个。
不带 `full` 时仍是**补丁包**：不带顶层目录的覆盖归档（`...-windows-x64-pack-<name>.7z`），
解压到基础包根生效。当前两个档位都是全量包：

| 包 | 形态 | 定位 | 内容 |
| --- | --- | --- | --- |
| `vsdlssg` | 全量（`full: true`，`default: true`） | 默认档 | 基础包 + `vs-plugins/dlss45`、`vs-plugins/xessfg` 等四套引擎运行时 |
| `vs-aji` | 全量（`full: true`） | 完整版 | `vsdlssg` 的全部内容 + `vs-plugins/aji`（vsaji 插件、libaji、TensorRT / TensorRT-RTX 运行库、conf、8 个模型） |

`default: true` 的是**默认档**（最多一个，`common.default_pack()` 会校验），值也会写进
`PACK_INFO.json`。四个帧生成插件 DLL（`vdlssg` / `vxessfg` / `vvfg` / `vfsr4`）在**基础包**里，
落在 `vs-plugins/`，由 `MEMC_*.vpy` 首次使用时 `LoadPlugin`——不复制进
`vapoursynth/plugins/`，避免自动加载与手动加载各来一份。

补丁形态的内容白名单（`build/pack.py: FORBIDDEN_REL` / `verify.check_pack_archive`）：

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

`.github/workflows/build.yml`：每日定时 / 手动 / PR → fetch → assemble → smoke → verify
→ 打两个全量档位包并逐个校验 → 上传单个 artifact `mpv-playkit-pre-windows-x64`
（含 `*-vsdlssg.7z`、`*-vs-aji.7z` 及各自 `.sha256`，14 天）。**故意不发布 release、不推 tag**，产物只走 artifact。
不 push 触发：本地全绿再推，避免每次推送失败都刷一封信。

`.github/workflows/sync-upstream.yml`：每天 UTC 03:00 跑 `python -m build sync`
（退出码 3 = 上游无更新），有变化就用 bot 身份提交 `chore: 同步上游 shaders`。
同步范围只有 `portable_config/shaders/`——基准配置的其余部分本地维护，不再跟随上游。

缓存策略：`actions/cache` 存 `.work/downloads`（CI 上没有共享工作区，缓存根就是这里），
key 用 `sources.lock.json` 的哈希——lock 一变缓存就失效，避免拿到旧资产。

## 失败排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Error parsing option vf` | 滤镜参数用 `:` 分隔，Windows 路径里的盘符冒号被误解析 | 用相对路径（smoke 就是这么做的）或 `--vf=vapoursynth="路径"` |
| `sources.lock.json 缺少组件` | 加了规则没钉版本 | `python -m build.pin --id <id> --url <url>` |
| `stage 含禁止目录: __pycache__` | 源码树把 `__pycache__` 提交进了 git（K7sfunc fork 曾经如此），或 stage 里跑了 Python 且没禁字节码 | `install_git_tree` 已固定剔除 `__pycache__`/`*.pyc`；还出现就用 `PYTHONDONTWRITEBYTECODE=1`（smoke 已内置） |
| 下载反复重试后失败 | 代理/网络；GitHub 资产会 302 到 `release-assets.githubusercontent.com` | 确认 `HTTPS_PROXY` 生效（urllib 直接读环境变量） |
| `找不到 7z 或 bsdtar` | 本机没有 7z | Windows 10+ 自带 `tar.exe` 可解 7z；否则装 7-Zip 或设 `SEVEN_Z` |
