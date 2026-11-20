# 设计决策记录

按时间顺序记录"为什么这样做"。改设计前先读这里，避免把已经讨论过的坑再踩一遍。

## 1. mpv 二进制走上游预构建，不自编（2026-11-20）

- **决策**：Windows x64 的 `mpv.exe` 直接取 [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake) 的官方 7z，只挑 `mpv.exe`、`mpv.com`、`d3dcompiler_43.dll`。
- **原因**：自己编 mpv 需要 MSYS2 + 完整工具链，产物差异也无法和上游对齐；而本项目要维护的是**配置 + 帧服务器工具集**，不是 mpv 本身。参考项目
  [100pangci/mpv_PlayKit_TLS](https://github.com/100pangci/mpv_PlayKit_TLS) 同样不自编。
- **代价**：mpv 版本受上游发布节奏约束，`vf=vapoursynth` 是否可用要靠冒烟测试兜底（当前 build 可用）。

## 2. Python 与 VapourSynth 都取官方件，VSScript 运行时配置由随包脚本写（2026-11-20）

- **决策**：`python` = [python.org](https://www.python.org) 的 `python-3.15.N-embed-amd64.zip`（解到包根，`python315._pth` 补 `Lib\site-packages` 并开 `import site`）；
  `vapoursynth` = PyPI 的 `vapoursynth-82-cp312-abi3-win_amd64.whl`（解到 `Lib/site-packages`，6 个运行时 DLL 再复制一份到包根）。
- **原因**：hooke007 的 `py.3_14_3+vs.R73-portable.7z` 是二手拼装件，版本滞后且路径结构不透明；官方件版本可追踪（`build.pin` 直接钉 python.org / PyPI 的 URL 与 sha256），
  也符合本项目"追最新"的定位。
- **关键约束**：VS R82 起 `vsscript.dll` **不再在编译期链接 Python**，运行时顺序是：先看 `vsscript.dll` 上溯四层有没有 `python.exe`+`python3.dll`，
  否则读 `%APPDATA%\vapoursynth\vapoursynth.toml`。本包把 `vsscript.dll` 放在包根，四层上溯不可能命中，所以**必须有那一行 TOML**。
- **做法**：`portable_config/scripts/k7f_vs.lua` 在脚本加载期（早于文件/滤镜初始化）定位包根、算出 `python.exe` 的 mtime，写入
  `"<小写 vsscript.dll 全路径>" = ["<python.exe>","<python3.dll>","<mtime>"]`。
  两个必须遵守的细节：① 键必须是**整条路径的小写**（VS 侧用 `LCMapStringEx(LCMAP_LOWERCASE)` 归一化后逐字节比较）；
  ② 路径里反斜杠要写成 `\\`（VS 的 `unescapeTOMLString` 会把单个反斜杠吞掉）。
- **代价**：包根多一份 ~13.7 MB 的 DLL 副本；用户首次运行会在 `%APPDATA%\vapoursynth\` 落一行配置（脚本会顺带清理指向已消失目录的陈旧行）。

## 3. 规则与版本分离：manifests 管怎么装，lock 管装哪一版（2026-11-20）

- **决策**：`manifests/components.yml` 只写 `kind / members / exclude / install_to / paths` 这类**规则**；
  `sources.lock.json` 写 `version / url / sha256 / size` 这类**版本**。`build.pin` 负责改 lock。
- **原因**：装配逻辑与版本号解耦，换版本只 diff 一个 JSON；同时 lock 是"唯一真相"，产物可追溯到确切字节。
- **纪律**：不手改 lock，一律 `python -m build.pin`；`BUILD_INFO.json` 里带 `inputs_hash`（构建代码指纹）和 `lock_digest`（组件指纹）。

## 4. 上游配置整目录同步，本仓库只加"旁边的东西"（2026-11-20）

- **决策**：`build/sync.py` 把 `hooke007/mpv_PlayKit` 的 `portable_config/` 和 `installer/` 整目录替换进来，其余目录（`build/`、`manifests/`、`docs/`、`.github/`）本地维护。
- **原因**：上游是纯配置仓库、无 CI、天天改配置。整目录替换让上游更新永远是"覆盖"，永不产生合并冲突；同时配置作者的手艺（uosc 界面、shader、快捷键方案）原样保留。
- **纪律**：不往 `portable_config/` 里加自己的文件——自定义功能一律放到别处（见下一条）。

## 5. 自定义功能进 K7sfunc 的 fork，不在本仓库（2026-11-20）

- **决策**：算法层 `mod_playkit.py` 与前端 `k7f_playkit.lua` 都写在 [o5-null/K7sfunc](https://github.com/o5-null/K7sfunc)，
  本仓库用 `kind: git-tree` 组件按 40 位 commit 抽取 `src/k7sfunc` 与那两个前端文件。
- **原因**：预设层本质是 K7sfunc 的"上层封装"，它依赖 `mod_scale/mod_memc/mod_dbdn` 的内部签名；放在同一个仓库里才能跟着上游演进而不用维持一个影子包。
  另起一个独立包会导致两处版本号、两处 API、两处发布节奏。
- **代价**：每次改功能要 push fork → `build.pin` 钉新 commit；`git-tree` 的 `paths` 是白名单，fork 里新增文件不会自动进包。

## 6. 产物带 `pre`：这是预览分支（2026-11-20）

- **决策**：项目名、产物名、artifact 名统一 `mpv-playkit-pre`。
- **原因**：本项目刻意追最新（最新 shinchiro mpv、最新 VS、最新 K7sfunc），不保证稳定；`pre` 是给使用者的明确信号。版本号仍用 `YYYY.MM.DD-<短哈希>`，因为日日构建。

## 7. 模型与插件不进包（2026-11-20）

- **决策**：`vs-plugins/models`、`madVR/madVR64.ax`、`librife_windows_x86-64.dll` 不打包，由使用者按需自行下载。
- **原因**：体积从 126 MB 膨胀到 GB 级，且与 GPU/驱动强相关；预览包的定位是"算法接线正确"，不是"开箱即用全部模型"。
- **代价**：`PLAYKIT_*` 在缺插件时会 warn 降级（例如 `DEBAND_STD` 缺 vszip、`NLM_STD` 缺 knlm），不会崩。

## 8. CI 只出 artifact，不发 release（2026-11-20）

- **决策**：`build.yml` 只 `upload-artifact`；不推 tag、不发 release。
- **原因**：先跑通构建链；发布节奏（每日？每周？）还没定，过早固定 tag 规则会返工。

## 9. 一个基础包 + 将来的"挡位依赖包"（2026-11-20）

- **决策**：包分两层。**基础包**是能直接播放的最小完整集合（mpv、yt-dlp、Python、VapourSynth、K7sfunc、上游配置），
  现在所有组件都在基础包里；将来的**挡位依赖包**（按 GPU/体积/算法分档）单独设计，暂不实现。
- **原因**：使用者的起点差异很大——有人只要一个能播的播放器，有人要插帧+超分。把所有东西塞进一个包只会让默认下载变成 GB 级；
  但拆包的前提是基础包先稳定，所以顺序是"先做基础包，再按需切片"。
- **约束**：组件清单要能随时被切分——现有 `components.yml` 的 `--with/--without` 与 `disable` 已经支持这种选择，
  将来加依赖包时只需新增包级清单（例如 `manifests/packs/*.yml`），不必改装配逻辑。
- **现状**：`yt-dlp` 按此归入基础包（mpv 的 `ytdl_hook` 会在包根找它），不设 `disable`。

## 10. 帧生成四引擎进 K7sfunc，插件与引擎包走拓展包（2026-11-21）

- **决策**：DLSS-G / XeSS-FG / NVIDIA VFG / AMD FSR4 四个模块追加在 K7sfunc 的 `mod_memc.py`
  （`DLSSG_NV` / `XESSFG_NV` / `VFG_NV` / `FSR4`，共用 `FRAMEGEN_HUB`），配套脚本放 fork 的
  `mpv/portable_config/vs/`（`MEMC_DLSSG_NV.vpy` 等四个），由 `components.yml` 的 `paths` 映射进包；
  插件 DLL 与引擎包不进基础包，由 `manifests/packs/framegen.yml` 提供（解压到包根，落到 `vs-plugins/`
  与 `vs-plugins/bin/<引擎>/`）。fork commit `e4217b5`，版本 `1.9.0+pre.4`。
- **原因**：引擎本体是第三方运行库 + sm86 解锁代理，按 NVIDIA RTX SDKs License 不能当独立产品分发，
  合计 43 MB；模块与脚本只是接线，属于算法层，按第 5 条进 fork。
- **代价**：基础包挂上这四个脚本时，缺插件会 `vs.Error`；缺引擎包则 DLSS-G / XeSS-FG 退回无解锁能力，
  VFG / FSR4 直接报错（这两个包不在公开 zip 里）。vpy 的引擎包探测必须同时兼容
  `vs-plugins/bin/<引擎>` 与 `vs-plugins/<引擎>` 两种布局——插件默认只在 `<DLL 目录>\<引擎>` 找，
  `bin/` 布局要靠显式 `proxy_dir` 参数。

## 11. 拓展包做成 overlay zip，插件与资源分两个目录（2026-11-21）

- **决策**：拓展包（"挡位补丁包"）是**不带顶层目录的 overlay zip**，解压到基础包根即叠加；
  里面允许四类内容——插件走 `Lib/site-packages/vapoursynth/plugins/**`，补丁包自己的 Python 运行依赖
  （如 `onnx`、`numpy`）走 `Lib/site-packages/` 下除 `vapoursynth/` 本体以外的位置，
  资源（引擎包、许可文本）走 `vs-plugins/**`，与基础包不同的配置走 `portable_config/**`
  （解压时直接覆盖，不做开关层），另加一份 `PACK_INFO.json` 说明包名与文件清单。
  清单在 `manifests/packs/<name>.yml`，版本仍进 `sources.lock.json`（键 `<pack>/<id>`）；
  `python -m build pack [--name <pack>]` 装配并出 zip，`build/verify.py: check_pack_archive` 校验。
- **原因**：VS R82 起插件只在 `Lib/site-packages/vapoursynth/plugins/`（含子目录）被自动加载，
  放 `vs-plugins/` 或设 `VAPOURSYNTH_PLUGIN_PATH` 都无效；而引擎包与模型必须留在
  `vs-plugins/` 下（`MEMC_*.vpy` 与 `vstrt` 的 `dllDir()/vsmlrt-cuda/` 都是按相对路径查）。
  两类东西机制不同、位置不同，混在一个目录会同时坏掉。overlay 而不重打基础包，是因为
  基础包 360 MB、帧生成引擎占 43 MB、TRT-RTX 运行库占 85 MB，多数人只要其一。
- **API 3 问题**：VS R80 起 `dropped api3 support`，而 `AmusementClub/vs-mlrt` 的官方二进制
  （含最新 test 版）全部按 API 3 编译，上游 issue #171 明确拒绝迁移。因此 TRT-RTX 包改用
  [AliceTeaParty/vapoursynth-api4-wheels](https://github.com/AliceTeaParty/vapoursynth-api4-wheels)
  的轮子：该仓库 vendored 上游源码树、在仓内改成 API 4、跟 `vs-mlrt-v16.x` 标签持续重打包，
  版本号带 `+alice.1`，钉 `vs-trt-rtx-cu129` + `vs-tensorrt-rtx-cu129` 成对更新。
- **实测**（R82 + RTX 3080）：叠加两个包后 `['vdlssg','vxessfg','vvfg','vfsr4']` 与
  `['trt_rtx']` 全部就位，`core.trt_rtx.Version()` 报 TensorRT-RTX `10500` / CUDA runtime `12090`，
  `DeviceProperties()` 认出 `NVIDIA GeForce RTX 3080`。
- **代价**：补丁包内容依赖上游 wheel 的目录布局（`plugins/vsmlrt/` 与 `vsmlrt-cuda/`），
  换版本时要重新核布局；单个第三方维护者（AliceTeaParty）若停更，需要退回"自己编 API4"或
  "把 VS 钉回 R79"。`pack.py` 的 `FORBIDDEN_REL` 会阻止补丁包覆盖 `mpv.exe`、`python.exe`、
  `vsscript.dll`、`vapoursynth.pyd`、`k7sfunc/` 等运行时本体（`portable_config/` 则允许覆盖）。

## 12. TRT-RTX 补丁包的依赖仍取 AliceTeaParty 的 API4 轮子（2026-11-21）

- **决策**：`tensorrt-rtx` 包继续钉 `AliceTeaParty/vapoursynth-api4-wheels` 的两个轮子
  （`vs-trt-rtx-cu129` + `vs-tensorrt-rtx-cu129`，版本 `16.2.2+alice.1`，成对更新），
  暂不自建 API 4 插件构建流水线，也不再找"现成的 API 4 二进制"。
- **原因**：`AmusementClub/vs-mlrt` 上游拒绝迁 API 4（issue #171），社区里当前只有这一个来源
  提供可直接钉住的 Windows 二进制。逐一核过其他候选：VapourSynth 核心贡献者 Ichunjo 的
  `Ichunjo/vs-mlrt`（tag `v17.0`/`v17.1`，源码确已全量 API 4，用 `mapGetIntSaturated` 一类新接口）
  **剥离了 `CMakeLists.txt`、`config.h.in`、`trtexec/`**，也没有 CI 与 release，取用它等于自己重建
  构建系统；`efschu/vstrt-rtx` 仍是 API 3（`propGetInt`）；`RyougiKukoc/vs-mlrt-api4` 已标为
  deprecated 并指向 Alice。换句话说，现在没有"既迁移完、又有产物"的第三方可选。
- **代价**：单个第三方维护者，停更或删库会让 CI 拉不到资产；`sources.lock.json` 的 sha256
  只能保证"同样的字节"，保证不了"还能下载"。
- **复核条件（出现任一即换方案）**：① 出现带 CI 产物的 API 4 fork；② 上游合并 API 4；
  ③ Alice 跨过一个 VS 版本周期未更新。届时的首选备选是自建：CUDA 13.4.2 网络安装器与
  TensorRT-RTX 1.7 SDK zip 都能免登录下载（`developer.download.nvidia.com`），TensorRT 头文件在
  `NVIDIA/TensorRT` 仓的 `include/`，VapourSynth 头文件在 wheel 的 `vapoursynth/include`，
  构建步骤照抄上游 `.github/workflows/windows-trt_rtx.yml`，产物发本仓 release 再按 sha256 钉住；
  次选是把 VS 钉回 R79 并显式 `LoadPlugin`（实测可用，代价是失去 R80–R82 的 GPU 修复）。

## 13. 基础包自带 VapourSynth 插件生态（2026-11-21）

- **决策**：`manifests/components.yml` 在 `vapoursynth` 之后补 10 个 PyPI 上的
  `vapoursynth-*` 轮子（`akarin`、`mvtools`、`fmtconv`、`zsmooth`、`bm3d`、`bwdif`、
  `vivtc`、`tivtc`、`vszip`、`znedi3`），`kind: whl` + `install_to: Lib/site-packages`，
  exclude 掉 `*.dist-info`；轮子里的 DLL 落在 `vapoursynth/plugins/`（含子目录），
  R82 递归扫描即加载。
- **原因**：K7sfunc 有 69 处 `_check_plugin`（`akarin`/`fmtc`/`mv`/`zsmooth`/`bwdif`/
  `znedi3`/`vszip`/`tivtc`/`vivtc`…），而此前的基础包插件目录只有 VSScript 自带的
  `avscompat.dll`——连 `CUGAN_NV` / `DPIR_DBLK_NV` 都会在第一步
  `ModuleNotFoundError: ... 缺失插件，检查项目 akarin` 上停住，绝大多数模块跑不起来。
  PyPI 是唯一现成的 API 4 二进制来源（`Jaded-Encoding-Thaumaturgy/vs-wheels` 只有
  fmtconv/ffms2/mlrt）。
- **故意不带的**：`vapoursynth-bilateralgpu`（47 MB，只服务 `bilateralgpu_rtc` 一个模块）；
  `nnedi3`/`eedi2`/`miscfilters`/`vsutil`（PyPI 无此包）。
- **代价**：基础包体积 +约 65 MB；插件版本进了 `sources.lock.json`，升级要重钉。

## 14. TRT-RTX 包带模型与 Python 依赖，并对 `trt_rtx` 强制静态引擎（2026-11-21）

- **决策**：`tensorrt-rtx` 包除插件与运行库外，再带 `cugan`（3 个）与 `dpir` 的去块
  两个模型（`drunet_deblocking_color` / `drunet_deblocking_grayscale`），以及 7 个
  Python 轮子（`onnx`、`onnxconverter_common`、`numpy`、`protobuf`、
  `typing_extensions`、`ml_dtypes`、`packaging`）；K7sfunc 侧 `_trt_backend` 对
  `core.trt_rtx` 强制 `static_shape=True` 并丢弃 `min/opt/max_shapes`。
- **原因**：vstrt 建引擎是在 Python 里 `import onnx` 读图、推形状、转 fp16，而包里是
  embed Python（无 pip、无 site-packages 依赖）；实测缺 `onnx` 时 `CUGAN_NV` 直接
  `ModuleNotFoundError: No module named 'onnx'`，缺 `typing_extensions`/`ml_dtypes`/
  `onnxconverter_common` 也是一层层挡在同一个函数里。动态形状引擎在 cugan 这类网络上
  必崩在 `cudnn_graph_utils.h:421 CHECK(false) failed. cuDNN graph compilation failed.`
  （`enqueueV3` 里 Myelin `shapeChangeHelper`），静态引擎三用例（CUGAN 静态/动态、
  DPIR）在 RTX 3080 上全部出帧。
- **代价**：包体从 85 MB 涨到约 365 MB；带上全部四个 `drunet_*.onnx`（各约 130 MB，
  合计 522 MB）会到 606 MB，因此只装 DPIR_DBLK_NV 用得到的两个去块模型（model 2/3），
  去噪用的 `drunet_gray` / `drunet_color` 由用户自己丢进 `vsmlrt/models/dpir/`。
  静态引擎按分辨率建，换尺寸要重建一次（引擎缓存在 `vsmlrt` 的 engine 目录）。
- **不考虑 7z 打包**：实测 130.6 MB 的 `drunet_deblocking_color.onnx`，deflate6/9 都是
  121.3 MB（−7.1%），LZMA2 `preset=6` 120.6 MB、`9|PRESET_EXTREME` 120.5 MB（−7.7%）——
  整个包装换成 7z 只省约 5 MB，却要求用户装 7-Zip 才能解，代价不值。
- **细节**：这 7 个 Python 轮子进包时**不能删 `*.dist-info`**——`onnx.__version__` 是读分发包
  元数据得来的，删掉后变成 `'unknown'`，`onnxconverter_common` 里的 `packaging.Version()`
  直接抛 `InvalidVersion: Invalid version: 'unknown'`（实测只在真实包树暴露，overlay 测试树
  带 dist-info 时正常）。
- **附带修好的三处上游 bug**（`_external/vsmlrt.py`）：`get_plugins_path()` 对 API 4 的
  `str` 路径调 `.decode()`；`tensorrt_rtx()` 调 `get_engine_path()` 少传 `int8`/`fp8`；
  `tensorrt_rtx()` 给 builder 下发 `-CUDNN`（TRT-RTX 只认 `EDGE_MASK_CONVOLUTIONS` /
  `JIT_CONVOLUTIONS`，会报 `Unknown tactic source: CUDNN`）。


- **`vf=vapoursynth` 的路径**：mpv 滤镜参数用 `:` 分隔，Windows 盘符会被当成参数分隔符。冒烟测试因此 `cwd` 到 stage 后用相对路径。
- **`python3xx._pth` 模式下 `PYTHONPATH` 无效**：`vs-scripts/` 是 `._pth` 里写死的搜索路径，所以 `k7sfunc` 要么进 `Lib/site-packages`，要么进 `vs-scripts/`。
- **上游 `mpv.conf` 里有空值选项**：`include=` / `vulkan-device=` 这类空值在新版 mpv（v0.42）上会打印 `Error parsing option ... (option requires parameter / could not be parsed)`。
  只影响该选项自身（回落默认值），上游目录我们不修改，冒烟测试把这类行归为噪声（`build/smoke.py` 的 `NON_FATAL`）。
- **Lua 里的 `mp.options` 必须显式 require**：新版 mpv 不再把所有子模块挂在 `mp` 表上，`mp.options.read_options(...)` 会报
  `attempt to index field 'options' (a nil value)`，要先 `local options = require("mp.options")`。
- **CI 的 Windows runner 是 en-US locale**：Python 默认 stdout 是 cp1252，中文日志会 `UnicodeEncodeError`。`build/common.py` 在导入时把 stdout 切到 UTF-8，workflow 里也设了 `PYTHONUTF8=1`。
- **`.gitignore` 不支持行尾注释**：`dist/   # 说明` 会变成含空格的模式而失效，注释必须独立成行。
- **codeload 经代理时 urllib 会握手中断**：`build/fetch.py` 在 urllib 三次失败后回退 `curl`。
- **本地跑完 `build sync` 后 `git status` 会冒出几百个 "M"**：Git for Windows 默认 `core.autocrlf=true`，而 sync 直接写入 tarball 的 LF 字节，索引里的 stat 缓存因此失效。文件内容其实一致（`git hash-object` 与 `HEAD:` 相同），`git add -A` 刷一次索引即恢复干净；本仓库已设 `core.autocrlf=false` 避免该现象。CI 上跑的是 Linux runner（默认不转换），不受影响。
- **sync 工作流与人工推送会抢 main**：`git push` 被拒后先 `git pull --rebase --autostash origin main` 再重试，最多三次。
- **vpy 里的 `__file__` 定位必须在 `if not hasattr(core, "<插件>"):` 之外**：发行包里插件由 `vs-plugins/` 自动加载，
  `hasattr` 为真、整块不执行；把 `_here = os.path.dirname(os.path.abspath(__file__))` 写在块内，
  后面新加的引擎包探测段就会 `NameError: _here`。
- **帧生成三件事**：一个进程只支持一种帧尺寸（换分辨率要重启）；NGX 每进程只能初始化一次（`vdlssg` 与 `vxessfg`
  不能同进程）；插件只改帧数不改 fps，自己拼 vpy 时要 `AssumeFPS`（模块已做）。
- **`dlss45` / `xessfg` 引擎包里的 `dlssg_sm86/logs/` 必须预先存在**：代理不建目录，缺了是零日志静默失败。
- **VS R80 起不再支持 API 3 插件**：`AmusementClub/vs-mlrt` 的官方二进制全是 API 3，在 R82 上直接
  `Plugin ... uses API 3, which is no longer supported.`（在 R79 上只是"deprecated"警告）。要么用
  AliceTeaParty 的 API4 移植轮子，要么把 VS 钉回 R79 并显式 `LoadPlugin`。
- **插件只有放进 `Lib/site-packages/vapoursynth/plugins/` 才会被自动加载**（R82 会递归扫描子目录，
  所以 `plugins/vsmlrt/` 里放 `vstrt_rtx.dll` 有效）；`vs-plugins/` 与 `VAPOURSYNTH_PLUGIN_PATH`
  都不参与加载。R79 更旧：该目录不自动扫描，只能写 `HKCU\SOFTWARE\VapourSynth` 或显式加载。
- **wheel 的 `*.dist-info` 会留下目录条目**：`exclude: ["*.dist-info/*"]` 只过滤文件，zip 里仍会有
  `*.dist-info/` 目录，补丁包校验会因为"不明目录"失败——exclude 里要同时写 `"*.dist-info"`。
- **overlay zip 的目录条目同样要 `/` 结尾**，且校验时的白名单判断要先 `rstrip("/")` 再比前缀，
  否则 `Lib/`、`Lib/site-packages/` 这些前缀链会被误判成"越界路径"。
