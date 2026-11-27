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

## 15. 其余模型走 Release 资产，一族一个 zip（2026-11-21）

- **决策**：`tensorrt-rtx` 包除了内置 cugan 与 dpir 去块，还要带齐 K7sfunc 的 NV 算法能用的
  其余模型：通用超分 5 个、`ArtCNN/` 3 个、`rife/` 5 个、`rife_v2/` 5 个、`drba/` 16 个
  （fp32 与 fp16 各一套）。这些权重不进 git，而是打成 5 个 zip 发在本仓库的 Release
  （tag `models-v1`：`models-generic.zip`、`models-artcnn.zip`、`models-rife.zip`、
  `models-rife-v2.zip`、`models-drba.zip`），构建时按 `sources.lock.json` 下载。
- **原因**：34 个 onnx 共 492 MB，塞进 git 会让每次提交永久留一份、clone 全拉；Release
  资产可以整体替换（新 tag）而不污染历史。一族一个包是为了让用户能只取自己要的那族，
  拆包粒度与 K7sfunc 的 `models/<族>/` 目录一一对应，解压后直接落到 `vsmlrt/models`。
- **代价**：补丁包从 363.7 MB 涨到 841 MB（实测 2026.11.20-db0f758：stage 1070.1 MB，
  模型 zip 已是压缩态，再套进包几乎不缩）。
  不想全量的用户可以只装 `-pack-tensorrt-rtx.zip` 里的 cugan/dpir，其余从 Release 单取。
- **细节**：`.engine` / `.engine.cache` 是 TensorRT 在本机按显卡与驱动构建的缓存，**不分发**
  （`rife_v2/` 里那 16 个就是这样被排除的）；zip 用固定时间戳生成，同样的输入得到同样的
  sha256，便于 `sources.lock.json` 钉住。

## 16. fp16 引擎：转换前先净化模型（fork `1.9.0+pre.6`）

- **决策**：`_external/vsmlrt.py` 里 `tensorrt_rtx()` 不再直接
  `convert_float_to_float16()`，而是先跑 `fp16_source(model)`：① 删掉「`to` 等于输入类型」
  的 no-op `Cast`（并把引用改写到它的输入张量）；② 把所有「输入是整型」的 `Cast` 节点名
  收进 `node_block_list`，交给 onnxconverter 在边界自动插 Cast。缓存文件名后缀随之从
  `_blk` 改为 `_castfix`。
- **原因**：16-bit clip（RIFE / DRBA 内部用 `vs.RGBH`）要求 fp16 io，于是要先转 fp16 模型；
  但 TRT-RTX 1.5 (b114) 的 importer 会把 `Cast(int64 -> half)` 的输出当成 Float（ONNX 侧
  `infer_shapes` 明确是 half），于是报
  `ElementWiseOperation PROD must have same input types. But they are of types Float and Half.`
  ——逐点 blocklist 只会把失败点从 node 66 迁到 node 282，必须整类排除。DRBA 另有一个
  "float 逃逸"：原图里 `Cast(x, to=float32)`（x 本就是 float32）被转换后变成
  `Cast(half -> float32)`，把 fp32 带进 half 图，与 half 的 `Concat` 在 `/Add_10` 相撞，
  所以必须先删 no-op Cast 再转。
- **代价**：转换多一次 `infer_shapes`（秒级，只在首次建引擎时跑）；已转换过的旧
  `*_fp16*_blk.onnx` 会被忽略，用户首次升级后要重建一次引擎。
- **实测**（RTX 3080 / 720p）：`RIFE_NV` 引擎 3.06 ms/帧、`DRBA_NV` 15.52 MiB 引擎
  1.34 ms/帧；六用例（cugan 静态/动态、dpir 去块、ArtCNN、RIFE、DRBA）在真实包树上全绿。
- **不要**：把 `fp16_io` 设成 `False` 想绕过——vstrt 插件不做位深转换，8-bit clip 配
  fp32 io 的引擎会报 `bits per sample mismatch`，且 `tensorrt_rtx.exe` 也没有
  `--fp16` / 任何 IOFormat 开关，引擎 io 类型只能跟 ONNX 模型走。

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

## 17. aji 作为插帧引擎：插件进 plugins/、运行时留在 vs-plugins/（fork `1.9.0+pre.7`）

- **决策**：`PLAYKIT_MEMC` 新增 `aji` 引擎（`RIFE_AJI`，AnimeJaNai/libaji 原生 RIFE），
  引擎顺序 `rife_nv → aji → rife_dml → none`。依赖按两个目录拆开：`rife_aji.dll` 进
  `Lib/site-packages/vapoursynth/plugins/`（VapourSynth 自动加载），`aji/`（`aji.dll`、
  `aji_trt.dll`、`cudart64_13.dll`、`aji-runtime.json`、`trt/nvinfer_11.dll`、`conf/`、
  `rife/rife_v4.14.onnx`）进 `vs-plugins/aji/`（插件运行期按路径 dlopen）。
- **原因**：aji 与 vs-mlrt 的 RIFE 是两条独立路径——它自带 conf 与 onnx（conf 只支持
  RIFE-only 场景），一个目录即"引擎 + 模型"。`rife_aji.dll` 是 VS 插件，必须被自动加载；
  它 dlopen 的 TensorRT 运行库与权重是资源，混进 `plugins/` 会被 VS 当插件扫描并刷错误。
- **代价 / 限制**：只收 4:2:0 8/10bit（NV12/P010），factor 只支持整数（`fps_num % fps_den`
  不整除就在建滤镜时报错，降级链继续）；必须带完整 TensorRT 运行时（`aji_create` 无条件建
  IRuntime，lean `nvinfer` 只能建 IRuntime 不能建引擎）；每帧主机↔设备拷贝、实例内串行，
  吞吐低于 `rife_nv`——所以排在它后面。
- **暂不做补丁包**：vsaji 尚未发布可下载的 release（`o5-null/vsaji` 还不在 GitHub 上），
  二进制只能按上面的两个目录手工放；等它发版后再加 `manifests/packs/vsaji.yml` 并 pin。
- **实测**（RTX 3080）：640x360 P010 → 2x 出帧正常；`PLAYKIT_MEMC(engine="auto")` 在缺
  `trt/trt_rtx` 时自动落到 aji；`PLAYKIT_RUN(preset="memc", memc_engine="aji")` 全绿；
  24→60（5/2）按预期报"只支持整数倍率"并降级到 none。调试可用 `AJI_PLUGIN`（DLL）与
  `AJI_DIR`（运行时目录）覆盖。每次建滤镜会多一行上游噪声
  `Version: no return value(s) named aji, api, path`（插件注册签名问题，无害）。

## 18. vpy 参数桥：下行走 `user-data`，上行写 sidecar 文件（fork `1.9.0+pre.7`）

- **决策**：K7sfunc 的四个 `MEMC_*.vpy` 统一用 `k7f_bridge.py` 解析 mpv 注入的 `user_data`；
  vpy 初始化完成后把**实际生效**的参数写到同目录 `<脚本名>.k7f.json`，`k7f_vpypar.lua` 每 0.5 s
  轮询并在 OSD 上显示“设置/实际”两行。
- **原因**：`vf=vapoursynth` 没有 `.command` 回调，vpy 也读不到 mpv 属性，没有实时回写通道；
  写文件 + 轮询不依赖 IPC、不跨线程，是唯一稳的做法。报告与脚本同名同目录，是因为 vpy 不知道
  `~~`，绝对路径的盘符冒号又不能塞进 `user-data`。
- **代价**：OSD 最多 0.5 s 延迟；`vs/` 只读时上行失效（下行不受影响）；每部片多一个小 json，
  换脚本后旧 sidecar 不会自动删，靠 `pid`/`ts` 判断新旧。写盘用临时文件 + `os.replace`，
  被占用时重试 3 次再退回直接覆盖，失败只 warn 一次，不影响播放。
- **打包**：`k7f_bridge.lua`、`k7f_vpypar.lua` 必须加进 `manifests/components.yml` 的 k7sfunc
  `paths` 白名单；`vs/` 是整目录，`k7f_bridge.py` 自动随四个 vpy 进包。
- **未接**：`k7f_playkit.lua` 生成的 `~~/k7f_playkit.vpy` 与 `MEMC_RIFE_AJI.vpy` 还没有
  `publish()`，playkit 滤镜暂无“实际”行。

## 19. 自定义配置放 overlay/，sync 后自动叠加（2026-11-23）

> 已被第 24 条取代：基准配置改为本地维护，`overlay/` 与 `build/overlay.py` 已删除。

- **决策**：`portable_config/` 继续只存上游内容；本仓库自己的配置改动放 `overlay/`，
  按包根结构镜像。当前只有 `overlay/portable_config/playkit-preset.conf`。
  `build.sync` 替换完上游目录后调用 `overlay.apply(ROOT)`：复制 overlay 文件，并在
  `portable_config/mpv.conf` 末尾补一行 `include = "~~/playkit-preset.conf"`；
  `build.assemble` 打包前对 stage 再执行一次同样的叠加。`overlay/` 纳入
  `inputs_hash`，自定义配置变化会反映到 `BUILD_INFO.json`。
- **原因**：上游 `portable_config/` 是每日整目录替换，直接改 `portable_config/mpv.conf`
  会在下一次 sync 被删掉；用户明确要求保留自行修改的配置。用 overlay + include 片段，
  既不阻止上游 `mpv.conf` 更新，也不依赖用户手工备份。
- **代价 / 边界**：overlay 里如果放大文件，会整文件覆盖上游同名路径；目前只放一个小 preset。
  `mpv.conf` 的 include 行由 `build/overlay.py` 自动补，**不要手动编辑上游副本里的自定义项**，
  否则下一次 sync 会被删。
- **首次落地**：preset 包含 `profile = playkit` 与 `[playkit]`
  （`d3d11-flip=no`、`d3d11-sync-interval=0`）；`portable_config/mpv.conf` 末尾的 include
  由构建链维护，实际文件在 `overlay/portable_config/playkit-preset.conf`。

## 20. mpv 改用自维护构建，发行物是平铺 zip（2026-11-23）

- **决策**：基础包的 `mpv` 组件不再取 shinchiro 的 7z，改为取
  [o5-null/mpv](https://github.com/o5-null/mpv) release 上的
  `mpv-x86_64-playkit-<版本>.zip`（`kind: archive`、`extract: zip`、`install_to: .`）。
  zip 无顶层目录：`mpv.exe`、`mpv.com` 加 MSYS2 CLANG64 的动态依赖闭包平铺在根。
  打包脚本 `mpv-src/scripts/package_windows.py` 用 `objdump -p` 递归解析导入表；
  CI 在 `mpv-src/.github/workflows/playkit-windows.yml`（tag `playkit-*` 时发 release）。
- **原因**：帧倍增要走 `vf_playkit`，必须 fork mpv 源码；shinchiro 的构建里没有这个滤镜，
  而且他的发行物是 7z——本机与 CI 都没有 7z 解压/生成能力（只有 bsdtar 回退）。
  用动态链接的平铺 zip，既能让 `mpv.exe` 直接跑，也能让 `build.pin` 用普通
  `urllib`/`gh` 取件，不需要额外解压器。
- **代价 / 边界**：包从 ~30MB 级涨到 ~60MB 级（DLL 闭包）；`d3dcompiler_43.dll` 不再随包，
  `verify.check_stage` 也去掉了这一必需项（mpv 自带的 D3D11 路径不需要它，只有旧 dlss45
  代理的 `version.dll` 链路才用到，属于引擎包的事）。本地试构建用
  `PLAYKIT_MPV_ARCHIVE=<zip>` 覆盖下载，`BUILD_INFO.json` 会写实际 sha256 并标 `overridden`。

## 21. 补丁包拆两档，并改为全量包交付：vsdlssg 默认、vs-mlrt 可选（2026-11-23）

- **决策**：四个帧生成插件 DLL（约 0.6MB）进**基础包**，落在 `vs-plugins/`，由
  `MEMC_*.vpy` 首次使用时 `LoadPlugin`（不复制进 `vapoursynth/plugins/`，避免双份加载）。
  档位拆成 `manifests/packs/vsdlssg.yml`（`default: true`，装 `vs-plugins/dlss45`、
  `vs-plugins/xessfg` 以及 vfg / fsr4 两套运行时）和 `manifests/packs/vs-mlrt.yml`（原 tensorrt-rtx 整体改名，
  lock 键改为 `vs-mlrt/*`）。两个清单都带 `full: true`：`assemble_pack` 先把基础包装进
  同一个 stage（`assemble(version, stage=...)`），再叠档位组件，产出与基础包同构的全量 zip
  （`...-windows-x64-<name>.zip`）；补丁形态（无顶层目录的覆盖 zip）代码保留但当前不用。
- **原因**：原先 `framegen` 包既带 DLL 又带引擎，和"默认档"要表达的东西混在一起；
  用户希望大多数人只下一个轻量默认包就能跑帧生成，TensorRT-RTX 作为可选推理档。
  进一步地，用户明确"现在两个包都是全包，暂时没有补丁包"——补丁包要求用户先解基础包再覆盖，
  对普通用户是额外一步，且覆盖式解压出错就毁基础包；全量包各自独立、可并行下载、
  换档只需换目录。
- **代价 / 边界**：默认档从 ~43MB 涨到 ~498MB（多了自维护 mpv 的 DLL 闭包、基础包本体与 vfg/fsr4 运行时），
  vs-mlrt 到 ~1.09GB（stage 1.65GB）；磁盘上两个 stage 各占 ~915MB / ~1.65GB。`PACK_INFO.json` 增加
  `full` 字段，`verify.check_full_pack_archive` 校验全量包（唯一顶层目录 + 基础必需项 +
  `PACK_INFO.full` 为 true），`check_pack_archive` 会自动识别形态。
  `common.default_pack()` 保证最多一个默认档。
- **aji 暂缓**：`vsdlssg` 里的 `vsaji` 组件先 `disable: true`（运行时与 RIFE 模型都不装），
  等 vsaji 定版后再 `build.pin --pack vsdlssg --id vsaji --file <zip>` 并用
  `--with vsaji` 试装；部署布局仍按第 17 条（插件进 plugins/、运行时进 `vs-plugins/aji/`）。

## 22. 默认档/推理档都改 `idle = yes`，双击 `mpv.exe` 不再闪退（2026-11-23）

> 机制已被第 24 条取代：`idle = yes` 现在直接来自基准 `portable_config/mpv.conf`，
> `overlay/` 与 include 行都不再存在；行为不变。

- **决策**：在 `overlay/portable_config/playkit-preset.conf` 顶部（`profile = playkit` 之前）加全局
  `idle = yes`。该文件由 `mpv.conf` 第 381 行 `include` 在末尾读入，顺序上覆盖上游第 50 行的 `idle = no`。
- **原因**：上游 PlayKit 配置是 `idle = no`，且 `mpv.conf` 里没有默认播放入口；无参数双击
  `mpv.exe` 时 mpv 打开后立即以 exit 0 退出，用户看到的是"双击没反应 / 打不开"。
  这不是构建问题（带文件启动窗口与播放都正常），但默认包应当零配置可用。
- **代价 / 边界**：常驻意味着无参数启动后进程与窗口一直存在，需要用户关窗或 `q` 退出（与
  PotPlayer/VLC 的一致行为）；不影响带文件启动、命令行批处理与 `--no-config` 场景。
  只改我们自己的 overlay 文件，不动上游 `portable_config/mpv.conf`。

## 23. 出包默认改 7z 最高压缩率，zip 仅作回退（2026-11-23）

- **决策**：`build/package.py` 默认 `7z`（`-t7z -mx=9 -m0=lzma2 -md=128m -mfb=273 -ms=on`，
  时间戳三项关闭），`--format zip` 走原来的确定性 zip。`build/sevenzip.py` 负责定位、创建、
  列名与读成员（`verify` 读 `PACK_INFO.json` 也从 7z 里取）。
- **原因**：全量包内容以 DLL/运行时为主，7z 收益远超第 13 条当时对模型 zip 的估计——
  实测 vsdlssg 498.1MB → **337.7MB**（-32%），vs-mlrt 1086.0MB → **680.9MB**（-37%）。
  用户明确要求"使用最高压缩比率 7z"。
- **代价 / 边界**：用户需 7-Zip（或兼容 7z 的解压器）；构建机需 `7z.exe`，查找顺序
  `PLAYKIT_7Z` → `PATH` → 注册表 `SOFTWARE\7-Zip` → `C:\Program Files\7-Zip`
  （本机 winget 装到 `C:\software\7-Zip`，注册表已登记）。7z 无 zip 那样的固定时间戳，
  字节级可复现性弱于 zip（内容与 `verify` 结果一致），需要严格复现时用 `--format zip`。
  CI 侧 `.github/workflows/build.yml` 校验与上传改 `*.7z` + `*.sha256`。
- **第 13 条不再适用**：那条讲的是把"模型 zip"再套一层，收益只有 ~5MB；现在压缩的是
  整个包的 DLL/运行时闭包，且 7-Zip 已成为本机与 CI 的既有依赖。

## 24. 基准配置取自 mpv-lazy 最后发版，档位差异改由配置清单生成（2026-11-23）

- **决策**：
  1. `portable_config/` 不再跟随上游 PlayKit 每日覆盖，改为以 `测试环境\mpv-lazy\portable_config`
     （mpv-lazy 最后发版）为基准、**本地维护**；上游只保留 `shaders/` 的整目录同步
     （`build/sync.py: SYNCED_DIRS = ("portable_config/shaders",)`），`installer/` 冻结不再同步。
  2. 新增 `manifests/config.yml`：`presets` 定义 VF 预设（`key` / `vpy` / `label` / `requires`），
     `packs` 定义每个档位包启用哪几个。`build/config.py` 用它重写 `input_uosc.conf` 与
     `menu.conf` 的 `# >>> playkit-config:vf` 标记区，并裁掉 `vs/` 里未启用的 `.vpy`。
  3. `assemble --pack <name>`（`pack.py` 里全量包自动传本档包名，组件装完再重算一次）；
     `python -m build config --stage <dir> --pack <name>` 可对已有 stage 单独重算。
  4. 删除 `overlay/` 与 `build/overlay.py`；`playkit-preset.conf` 的 `idle = yes` 由基准
     `mpv.conf` 直接提供，第 19、22 条的 overlay 机制作废。
- **原因**：用户的原话是"构建的 portable_config 引入了太多我不知道的脚本和设置"，
  要求以自己长期使用的 mpv-lazy 配置为基准；而各档位包（vsdlssg 带四个帧生成引擎、
  vs-mlrt 带 TRT 推理）本来就需要不同的按键与 vpy 集合。用一份清单生成差异，
  比维护两三份完整配置副本更容易看懂、也不会漂移。
- **代价 / 边界**：
  - 放弃逐日跟随上游配置更新；上游 `mpv.conf` / `menu.conf` / `scripts/` 的改动需要手工挑选，
    只有 `shaders/` 自动跟。
  - 基准里点名的 vpy 有 11 个，每个包只留启用的那几个；未启用的在按键文件里保留整行注释并
    注明缺哪个组件（`requires`），用户能看到"为什么这个键没有"。
  - `portable_config/` 的配置文本（含 `scripts/`、`vs/`）现在进 `inputs_hash`；
    `shaders/`（142MB）与 `fonts/`（14MB）按资源处理，不进哈希。
  - 基准 mpv.conf 引用的字体 `LXGW WenKai Mono Lite`（13.9MB，OFL）随包入库。

## 25. 原生滤镜（零拷贝 DLSS-G）进菜单，并修好 menu.conf 的标记与禁用项（2026-11-23）

- **决策**：
  1. `manifests/config.yml` 增 `native` 段（`section` / `clear_label` / `clear_command` / `entries`），
     `build/config.py: render_native()` 在 `menu.conf` 的 "VF 滤镜" 与 "着色器" 之间生成
     "原生滤镜 (&P)" 段：`清空 (&C)` 与 `DLSS 帧生成 (&D)` → `2×`–`6×`，
     命令形如 `set hwdec d3d11va; vf set playkit:multi=2:dll=vs-plugins/vdlssg.dll:proxy_dir=vs-plugins/dlss45`。
     只有 `packs` 里列出的档位包（当前只有 `vsdlssg`）才生成整段，没有引擎的包不留点不动的项。
  2. 标记行一律追加 `hidden=true`；未启用的预设不再写成 `#` 注释，而是保留命令 + `disabled=true`
     （灰显不可点），标题里写清缺哪个组件。`input_uosc.conf` 是按键表，仍用 `#` 注释。
  3. VS 预设的命令前缀 `set hwdec auto-copy;`，原生滤镜的命令带 `set hwdec d3d11va;`；
     `清空` 同时 `vf clr playkit; set hwdec auto-copy`。
  4. `mpv-src: video/filter/vf_playkit.c` 的相对路径解析改为"先工作目录、再 mpv.exe 目录"
     （`pk_abs_path` / `pk_exe_relative_exists`），因为 NGX 只认绝对路径而工作目录会被
     快捷方式、文件关联改掉。
- **原因**：`select.lua` 解析 `menu.conf` 时只按 `\t+` 切分、不认 `#`，我们原来的 `# >>>`
  标记与"本包未启用"注释在实测的 `menu-data` 里全变成了空菜单项（27 项里就有 12 条垃圾）；
  而 `context_menu.lua` 只对 `hidden` / `disabled` 生效（`:209`、`:287`）。另一头，
  `vf_playkit` 只在 `imgfmt == IMGFMT_D3D11 && multi > 1` 时走桥，`hwdec=auto-copy` 拿到的是
  软件帧 → 静默直通、没有 2× 也不报错，所以命令必须顺带切解码模式。
- **代价 / 边界**：
  - 走原生滤镜必须 `hwdec=d3d11va`，切回 VS 预设时靠 `set hwdec auto-copy` 还原；两边都改
    `hwdec` 会触发解码器重建（`UPDATE_HWDEC` → `queue_seek` 回当前时间点，不重开文件）。
  - 引擎一进程一帧尺寸，换分辨率要重开文件；桥只有 DLSS-G，XeSS/VFG/FSR4 仍只有 VS 路径。
  - 改了 `vf_playkit.c` 就得重编 mpv、重新 `build.pin` 钉新的 release，包内 mpv 才认相对路径。

## 26. 出包压缩档从 9 降到 7（2026-11-24）

- **决策**：`build/sevenzip.py` 的 `SEVENZIP_ARGS` 改 `-t7z -mx=7 -m0=lzma2 -ms=on`（其余时间戳
  与 `-bd -y` 不变），并把 `-md=128m -mfb=273` 删掉——那两项是九档的字典与匹配参数，写回去
  等于把九档套在七档上，时间省不下来。
- **原因**：全量档位包（947MB / 1685MB）用 `-mx=9` 固实压缩要 5~8 分钟且吃满 CPU，用户在
  构建环节明确要求降到七档。体积代价实测约 3~5%，换来打包时间降到三分之一左右。
- **代价 / 边界**：产物体积与 `SHA-256` 都变了，旧 `.sha256` 不再对应；内容一致性仍由
  `python -m build verify --pack` 把关。需要极限体积时可临时改回九档，但不要只改 `-mx`、
  又保留 `-md/-mfb`。

## 27. 安装器的解包临时目录一律 `try/finally` 清理（2026-11-24）

- **决策**：`build/assemble.py` 的 `install_mpv` / `install_archive` / `install_wheel` /
  `install_git_tree` 把"解包 + 复制"包进 `try/finally: common.remove_tree(tmp)`。
- **原因**：`common.make_temp_dir()` 只做 `tempfile.mkdtemp(dir=WORK_DIR)`、自己不登记清理，
  四个安装器建完从不删除 → 每成功构建一次就在 `.work` 漏一份完整解包副本。叠加被 `taskkill`
  中断的几次构建，`.work` 累积到 **51.57 GB**，把 `E:` 写满（`Free 475136`），并行档位包因此
  双双 `WinError 112` / `Errno 28` 失败。
- **代价 / 边界**：进程被强杀（`taskkill /F`、系统重启）时 `finally` 不执行，仍会残留；那种
  情况靠手动清 `.work`（保留 `*-local.*` 覆盖件与测试脚本）。

## 28. VF 预设菜单项挂在 `VF 滤镜` 之下，标记行随之缩进（2026-11-24）

- **决策**：`portable_config/menu.conf` 里 `vf` 那一对标记行改成缩进一层
  （`\t# >>> playkit-config:vf（由 manifests/config.yml 生成，勿手改）\thidden=true`），
  预设行保持一层缩进。`build/config.py` 新增 `MENU_VF_INDENT = "\t"`，`check()` 断言标记行
  确实缩进，否则构建直接失败。
- **原因**：`select.lua:1393-1412` 用行首缩进建树。标记行在根层时，缩进一层的
  `预设 补帧 …` 就成为"隐藏标记的子菜单"；Windows 原生菜单 `build_menu()` 先递归建子菜单
  再判 `if (fState == -1) // hidden continue;`（`mpv-src/video/out/win32/menu.c:150-161`），
  父项被跳过时整棵子树跟着消失——用户看到的右键菜单变成 `VF 滤镜 > 只有 清空 (&C)`。
  `倍数 (&M)` / `原生滤镜 (&P)` 是根层段标题，所以只有 VF 预设这一块出问题。
- **代价 / 边界**：`splice_block()` 按 `strip()` 后比较标记行，缩进不影响拼接；但模板
  `portable_config/menu.conf` 与任何手写的 stage 配置都必须带那个 `\t`，否则 `check()`
  拦下。`menu-data` 里会多出一条 `# <<< playkit-config:vf`（hidden），无害。

## 29. 帧生成 DLL 改用 vs-framegen 0.2.1 发行资产，不再需要本地覆盖件（2026-11-24）

- **决策**：`sources.lock.json` 里指向 vs-framegen 发行 zip 的组件（`vs-framegen-dlls` 与
  `vsdlssg/engine-framegen`）一起升到 `0.2.1`
  （`https://github.com/o5-null/vs-framegen/releases/download/v0.2.1/vs-framegen-0.2.1.zip`，
  253831573 B，`sha256 578ccafe694d3dd4ba64131aca41aa9e14b103ec30652a1fc2451d64c7253fc5`）。
  构建不再需要 `PLAYKIT_LOCAL_VS_FRAMEGEN_DLLS`。
- **原因**：0.2.0 的 `vvfg.dll` 在同一进程里反复初始化会崩（`0xC0000005`，事件日志
  `出错模块名称: unknown`、`偏移 0x0`）。根因在 `vs-dlssg/src/vfg_session.cpp`：`patchIat`
  把 `nvcuda.dll` 的 `cuDeviceGetAttribute` / `cuModuleLoadData` 换成指向本 DLL 的钩子，
  真函数指针只存在本 DLL 的静态量里；VapourSynth 销毁环境时会卸载插件 DLL，同基址重载后静态量
  归零、IAT 仍指向旧钩子 → 钩子空调用。0.2.1 用 `pinPluginImage()`（`GET_MODULE_HANDLE_EX_FLAG_PIN`
  加 `std::call_once`）钉住映像，并在 `patchIat` 开头无条件重新 `GetProcAddress` 取真指针。
- **代价 / 边界**：`vs-framegen-dlls` 与 `vsdlssg/engine-framegen` 两条 lock 指向同一个
  253.8 MB 资产（前者取顶层四个 DLL，后者用 `include` 取四棵运行时目录），`fetch` 的缓存按
  sha256 命名，所以只下一份、只存一份；发行包内 `vs-plugins/fsr4/shader_cache` 已剔除（测试跑出来的
  vkd3d 运行时缓存，不该进发行包）。

## 30. 档位包的四颗引擎合并成一个 `engine-framegen` 组件（2026-11-24）

- **决策**：`manifests/packs/vsdlssg.yml` 里原来的 `engine-dlss45`、`engine-xessfg`、`engine-vfg`、
  `engine-fsr4` 四条组件合并为一条 `engine-framegen`（`include` 四棵目录、`provides` 取并集 15 条），
  lock 里对应的 `vsdlssg/engine-*` 四条记录合并为 `vsdlssg/engine-framegen` 一条（36 → 33 个组件）。
- **原因**：`9dd2d60` 之后四颗引擎已经共用同一个发行 zip，但组件仍是四条、lock 仍是四条，而
  `build/fetch.py` 的缓存按**组件 id** 分目录（`downloads/<id>/<文件名>`），于是同一个 253 MB 资产
  在一次 `pack --name vsdlssg` 里被下载 4 次（加上基础包那条共 5 份、约 1.27 GB）。合并组件同时把
  缓存改成按 sha256 命名（`downloads/_sha256/<hash>/<文件名>`），彻底消掉重复下载。
- **代价 / 边界**：四颗引擎不再能各自单独 pin 版本——它们本来就在同一个 zip 里，分开 pin 只会制造
  不一致；`install_archive` 的 `include` 白名单仍逐条列出四棵目录，将来资产里新增引擎目录需要手工加。

## 31. vpy 侧的参数桥并入 K7sfunc，`MEMC_*.vpy` 只留用户选项（2026-11-25）

- **决策**：删除 `mpv/portable_config/vs/k7f_bridge.py`，逻辑搬到 K7sfunc 的
  `src/k7sfunc/mod_vpy.py`（fork `1.9.0+pre.8`）：`FRAMEGEN_VPY` 一次调用负责 user_data/
  环境变量解析与钳制、插件定位（`VPY_LOAD_PLUGIN`）、补帧主流程（预缩 / YUV 直通 /
  帧率兜底）和上行报告（`VPY_PUBLISH`）。四个脚本从 147–157 行降到 39–42 行。
- **原因**：四个 vpy 各自抄了五段同样的样板（sys.path + `import k7f_bridge`、手写
  `_parse_user_data`、环境变量覆盖、user_data 覆盖、插件候选列表），改一处要同步四遍；
  而 K7 的其它 vpy 本来就是"用户选项 + 一次 `k7f.*` 调用"的写法。顺带把 `vxessfg` 的
  倍率表改成只放行 2（与上一轮 `a01dad1` 的脚本钳制对齐，模块层之前仍写着 2–4）。
- **代价 / 边界**：脚本不能再单独拷出 `vs/` 目录运行（现在依赖 `import k7sfunc`）；
  参数键名与 `<脚本>.k7f.json` 格式没变，`k7f_bridge.lua` / `k7f_vpypar.lua` 不用改，
  但 `k7f_vpypar.lua` 的参数表注释已指向 `FRAMEGEN_VPY_OPTIONS`。`vs/` 是整目录复制，
  删掉 `k7f_bridge.py` 后下一次构建自然不再带上它，不需要动 `components.yml`。


## 32. 补帧滤镜跑分脚本：installer/ 开一个进包的例外（2026-11-25）

- **决策**：新增 `installer/mpv-补帧滤镜跑分.bat` + `mpv-FilterBench.conf` +
  `mpv_filter_bench.lua`（另有出报告用的 `mpv_filter_bench_report.ps1`），并在 `components.yml`
  里加 `bench-scripts`（kind=repo-files）把它们落到包的 `installer/` 下。**只放这四个文件**，
  installer/ 里其余上游脚本仍然冻结、仍然不进包。
- **原因**：用户拿了包想知道"我这台机器 VS 滤镜和原生滤镜哪个快、该开几倍"，就得有一个
  双击可用的入口；跑分必须用真视频文件（截图/合成源直接喂 `--vf` 时滤镜链建不起来，
  拿不到 D3D11 帧，滤镜会静默不执行），也只能在分发包里跑（要 `mpv.com` / `portable_config` / `vs-plugins`），
  所以脚本必须随包走。为了不动既有冻结约定，用独立组件精确放行三个文件，而不是解冻整个目录。
- **做法要点**：
  - 分辨率不换素材：`--vf=d3d11vpp=scale=W/SRCW,<补帧滤镜>` 在 D3D11 视频处理器里按宽度缩放，
    1080p/2k/4k 只是倍率不同（2.35:1 片源 4k 档得到 3840x1632，符合"4K 宽度"）。
  - 度量口径是**端到端呈现吞吐**：`--untimed --frames=600`，Lua 在 `playback-restart` 记时、
    `end-file` 收尾，`out_fps = frames/elapsed`，`src_fps = out_fps/multi`，NGX 初始化时间不进分母。
    呈现端必须 `d3d11-flip=no` + `d3d11-sync-interval=0`，否则被 vsync/DWM 压到 66fps。
  - 交互：拖入/粘贴素材 → 提示分辨率（空=1080p 2k 4k 全测）→ 提示倍数（空=2）；
    也给 `bat "视频" "1080p 4k" 6` 这种免交互用法，便于批处理。
   - **素材可以不准备**：直接回车就用 `av://lavfi:testsrc2` 编一段 10 秒 1920x1080 片段缓存到
     `%TEMP%\mpv-filter-bench\bench-src.mp4`（必须 mp4：matroska 输出写不出帧率，vpy 拿到 0 会
     报 `AssumeFPS: invalid framerate specified`；`--ofps` 这个选项不存在，加了产出 0 字节）。
   - 正式跑分前**预检**两条路径各 40 帧，在 `--log-file` 里找成功标记
     （VS：`[vapoursynth] initialized.`；原生：`playkit: vdlssg bridge ready`），找不到就整段跳过。
     原因是滤镜初始化失败时 mpv 只是 `Disabling filter ...` 继续播，会跑出 1300+fps 的假数字。
     顺带一个坑：mpv 自身日志走 **stdout**（Lua 的 `print` 也在 stdout），要留完整日志得用 `--log-file=`。
   - 跑完生成 `installer/report.txt`（系统 / CPU / 内存 / 显卡与驱动 / nvidia-smi / 播放器版本 +
     测试条件 + 结果表），由 `installer/mpv_filter_bench_report.ps1` 写，UTF-8 **带 BOM**
     （PS 5.1 读无 BOM 会按 ANSI，中文会乱）。它是第四个进包文件（同在 `bench-scripts` 里）。
   - **VS 滤镜不走全局 toml**：直接 `set VSSCRIPT_PATH=%CD%\Lib\site-packages\vapoursynth\vsscript.dll`。
     `vf_vapoursynth.c:819` 支持这个环境变量（`dlopen(getenv("VSSCRIPT_PATH"))`），而 site-packages
     里那份 DLL 往上四层正好是包根，能自己找到 `python.exe` / `python3.dll`，不需要
     `%APPDATA%\VapourSynth\vapoursynth.toml`。原因：本机 PATH 上的旧 `vapoursynth.exe config`
     会把那份 toml 写成 2 字段（R82 要求 3 字段、第三个是 `python.exe` 的 mtime），
     一旦被它重写，VS 滤镜就整段 `Failed to initialize VapourSynth VSScript library`。
     也就是说跑分依赖的是**包内**的 VSScript，不动用户机器上的全局配置。
- **代价 / 边界**：数字含呈现端开销（比 `PLAYKIT_TIMING` 的 process 大得多，1080p 2× 原生约
  34ms/对 vs 内部 5–8ms），是"能喂多快"而不是"滤镜占多少 CPU"；两种滤镜共用同一套 harness 才可比。
  已知坑：`--include` 必须写 `=`；`--vf=` 里的 `~~/` 不展开，要写相对包根路径；
  `--input=no` 会连 `--term-playing-msg` 一起关掉（探宽用不到它）；mpv 会把脚本名里的 `-`
  归一化成 `_`，`--msg-level` 前缀与脚本求值名要用下划线。包内中文文件名依赖 zip 的 UTF-8 标记，
  老解压工具可能显示成乱码（与 installer 既有脚本风格一致，暂不改名）。

## 33. 帧生成资产升到 vs-framegen 0.2.2、fork 钉到 1.9.0+pre.9（2026-11-26）

- **决策**：`sources.lock.json` 里 `vs-framegen-dlls` 与 `vsdlssg/engine-framegen` 一起升到 `0.2.2`
  （`https://github.com/o5-null/vs-framegen/releases/download/v0.2.2/vs-framegen-0.2.2.zip`，
  253832410 B，`sha256 bfa079362644a532b15be7a1c8796c653f9c7edbfd5d53f0db5e341c8038d289`）；
  `k7sfunc` 钉到 `83a830f`（`1.9.0+pre.9`，codeload tar.gz，`sha256 fa619e8bbdbc584d5dd4f69540717bbcde658546bb58d3a1ac365008fe3ed3f1`）。
- **原因**：0.2.2 让桥路径复用上一对的末帧当下一对的 seed（`generateTexturesMulti()` 的
  `needSeed` 判据 `lastPairIndex + 1 == pairIndex`），1080p 实测每对省掉约 9.5 ms 的 seed evaluate
  （桥内 process 中位约 38.6 ms/对）；同版还有 VVFG 默认档改 medium、同一对中间帧流水化
  （1080p medium −26%）、YUV full range 偏品红修复。`1.9.0+pre.9` 相对 pre.8 只多一个门控的
  `[vpy-debug]` 探针（`mod_vpy` 打 stage 与逐帧耗时），用来核对 `FRAMEGEN_VPY` 的实际开销。
- **代价 / 边界**：DLL 侧行为有变化（seed 省略、档位表），按档位包重跑预设时要以 0.2.2 为准；
  两条 lock 仍指向同一个 253.8 MB 资产，缓存按 sha256 命名所以只留一份；`vs-framegen-dlls` 取
  顶层四个 DLL，`engine-framegen` 用 `include` 取四棵运行时目录。`manifests/config.yml` 里四个
  预设的标题同时由 `DLC-vsNV` 改成 `DLC-vsFG`，与发行包名一致。

## 34. 构建产物与下载缓存统一到 `repos\`（子仓库留在根下）（2026-11-26）

- **决策**：本机各子仓库（`mpv-playkit` 本体、`k7sfunc`、`k7sfunc-wiki`、`mpv-src`、`ngxsdk`、
  `vsaji`）仍放在 `E:\code\dlssg-vfi\` 根下各自独立；**只有**构建产出的交付归档与下载缓存
  收进根下的 `repos\`。`build/common.py` 新增 `_shared_root()`：`PLAYKIT_SHARED_ROOT` 显式指定
  优先；否则仓库父目录下存在 `repos\dist` 或 `repos\.cache` 就用它（并兼容旧布局
  `<root>\repos\<repo>`）。命中时 `DOWNLOAD_DIR = repos\.cache\downloads`、`OUT_DIR = repos\dist`；
  `STAGE_ROOT` 仍是 `<repo>\dist\stage`（单包 0.6–1.7 GB，不放共享区，打包后保留供手测）。
  `build/fetch.py` 在下载前多一步：`repos\dist` 里有同名且 sha256 一致的归档就 `os.link`
  硬链接进缓存复用。
- **原因**：同一份 253.8 MB 帧生成资产、同一批 vsrife/models 组件在多个仓库各自的
  `.work\downloads` 里各存一份；产物又散落在各仓库 `dist\out`（本机 `mpv-playkit\dist\out`
  累积了 8 组历史 7z）。用户要求"子仓库不要收进 repos，只有构建的 release 要"，
  缓存也优先从共享处查找。
- **代价 / 边界**：不装共享根（CI checkout、仓库被单独拷走、父目录下没有 `repos`）时
  `DOWNLOAD_DIR` / `OUT_DIR` 完全退回旧路径，workflow 与 actions/cache 不用改；
  `repos\dist` 里的同名旧版本靠 sha256 判定，不匹配就照常下载，不会误用；
  本地 `.work\downloads` 从此闲置（可直接删）。
  搬目录踩过的坑：watcher 持有句柄时 `Move-Item` 会退化成复制+删除并在 `.git` 上报
  `Access is denied`，同卷搬目录要直接用 `move`（改名）或 `robocopy /MOVE`。

## 35. 跑分脚本加 VS-VFG 车道、全英文并改名 mpv-FilterBench.bat（2026-11-26）

- **决策**：跑分入口从 `installer/mpv-补帧滤镜跑分.bat` 改名为 `installer/mpv-FilterBench.bat`，
  四个脚本（bat / conf / lua / ps1）的注释、提示、TSV 表头与 `report.txt` 全部改成英文，
  bat 保持纯 ASCII + CRLF（不再 `chcp 936`）；同时新增一条 **VS-VFG** 车道
  （`vapoursynth + portable_config/vs/MEMC_VFG_NV.vpy`，multi 走 `VVFG_MULTI` 环境变量），
  每档分辨率依次跑 VS-DLSSG / VS-VFG / NATIVE 三条。
- **原因**：原生滤镜 `vf_playkit` 只导出 vdlssg 的 bridge（`vf_playkit.c` 取
  `vdlssg_bridge_create`，`bridge.cpp` 里 engine 固定为 Dlss），VFG 跑不了原生路径；
  英文输出便于把结果直接贴到 issue/论坛，也免掉 GB18030 批处理在非中文系统上的乱码风险。
- **代价 / 边界**：三条车道各自一个 mpv 进程，满足 DLSS-G 与 VFG 不能同进程加载的限制；
  VFG 每个内插点占一条 CUDA lane（约 1.5 GB 显存），4K + 高倍数在 10 GB 卡上会预检失败并
  整段跳过（脚本会提示，不算错误）；`manifests/components.yml` 的 `bench-scripts` 与
  `docs/mpv-filter-bench.md` 已同步新文件名。

## 36. 跑分先等帧率稳定再计时（排除模型预热）（2026-11-26）

- **决策**：`installer/mpv_filter_bench.lua` 不再从首个呈现帧起计时，而是以 0.1 s 间隔轮询
  "已呈现输出帧数"（`time-pos * src_fps * multi`），比较相邻两个 1 s 窗口的平均帧率，
  两者相差 ≤8 % 且各窗口 ≥8 帧时判定进入稳态，**从这一刻才开始计时**；随后继续测到
  `--frames` / 片尾，或稳态后再测满 3 s 且 ≥60 帧就提前退出。预热秒数写进 TSV 的
  `note` 列（`warm=2.1s`）。`--frames` 从 600 提到 3000，只当兜底上限（快速车道在预热里就
  能烧掉几百帧，600 帧的预算常常撑不到稳态之后）；自带的合成测试片从 10 s 加长到 30 s
  （`--frames=900`，缓存名改成 `bench-src-30s.mp4`，旧的 10 s 缓存不再复用），否则
  高帧率车道的片子在预热结束前就播完了。
- **原因**：NGX / bridge 初始化、模型加载、CUDA graph 捕获，以及 VFG 每个内插点各自一条
  CUDA lane 的预热，都要花 1–3 s 才到真实速度；把这段算进平均值会系统性低估吞吐，
  对 VFG（lane 越多预热越久）影响最大。用户实测数据被这段 ramp 拉低很多。
- **边界 / 代价**：稳态判定有两条兜底——`WARMUP_MAX=12 s` 内判不出来就"测剩下的"并在
  note 里标 `warm-timeout`；整段跑完都没稳态则写一行 `warmup-unfinished` 的横杠行而不是
  静默丢行。极慢车道窗口凑不够 8 帧会走 timeout 分支，但此时尾部本身已稳定，结果仍可用。
  预热逻辑对所有车道一视同仁（VS-DLSSG / VS-VFG / NATIVE），单次运行通常比原来更短。
- **修订（2026-11-27，帧数取证）**：帧数换算不能在收尾时实时读 `time-pos`——`end-file` 到达时该属性
  已经卸载成 nil，`est` 变成 0，脚本会退回 `--frames` 的兜底值（于是每行都写 3000 帧、帧率虚高）。
  现在改为在 `playback-restart` 之后用 `mp.observe_property("time-pos", "number")` 持续缓存最后一个
  有效值，帧数与计时终点都取这份缓存；计时起点 `t0` 也改用同一缓存的时间戳，保证分子分母对应同一帧区间。
  实测（993e00d-vsdlssg stage，1080p，multi=2，30 s 合成片，同一次会话）：VS-DLSSG 196.5 out fps（warm=2.2 s）、
  VS-VFG 150.2（warm=3.7 s）、NATIVE 75.5（warm=3.5 s），旧表同组合 314.0 / 188.7 / 111.9，虚高约 1.6× / 1.3× / 1.5×。
  帧数估算另用 `--frames=1200/1700/1900` 三档反查：1200/1700 在片尾前被帧上限截停、
  1900 才吃到 `filter output EOF`，说明真实输出帧数落在 (1700, 1900)，与 `time-pos*30*multi≈1800` 吻合。
  注意跨会话的绝对数值会成簇波动（同一组合见过 118–126 与 196–208 两簇，GPU 功耗/温度状态不同所致），
  横向比较必须取同一次会话跑出的整表。
- **修订（2026-11-27，单次运行 40 s 上限）**：新增 `RUN_MAX_S=40`——一次运行墙钟超过 40 s 就写一行
  `warm=..s,run-timeout` 的横杠行并 `quit`，不再硬等 `MEASURE_MIN_F=60`。原因：4K × 5/6 倍的 VS-VFG
  在 10 GB 卡上会爆显存转入共享内存分页，帧率塌到 0.2–1.2 fps，`warm-timeout` 之后照样要测满 60 帧，
  单格耗时 52–255 s 且数字没有意义；现在这类格子 40 s 内收工，表里显示横杠，整个 sweep 不会被一格拖死。

## 37. 「补帧参数」面板的入口由配置清单生成，与 multi 同进同退（2026-11-27）

- **决策**：`manifests/config.yml` 新增可选段 `vpypar`（`section / target / key`），
  `build/config.py` 据此渲染两处新标记区 `playkit-config:vpypar`：
  `input_uosc.conf` 的 ` V  script-binding k7f_vpypar/menu  #! VF 滤镜 > 补帧参数`，
  以及 `menu.conf` 的「补帧参数 (&V)」子菜单（打开面板 / 当前参数）。
  生成条件与 `multi` 段一致：本档位包启用了任一带 `multi: true` 的预设（即真的带帧生成）才出现，
  `base` 档位包两处都不生成。`check()` 同时校验「该出现时必须出现、不该出现时必须没有」。
- **原因**：入口属于打包链，不属于功能本身——K7sfunc fork 不知道某个档位包里有没有帧生成，
  而 `portable_config/` 的标记区按硬约束 1 只能由清单生成。`V` 在本仓库没有别的绑定
  （`v` 已给音频延迟），四个预设键位（`! @ $ % ^ & * ( ) _`）也不受影响。
- **边界 / 代价**：`vpypar` 段缺字段会被 `validate()` 直接拒绝；`config` 子命令要求 stage 里已有
  帧生成的 vpy（`prune_vpy` 会核对），空 stage 会报「启用的 vpy 不在包里」——用 dist 的
  `portable_config` 复制一份当 stage 即可快检，不必整包构建。

## 38. 原生滤镜的倍率跟随「倍数」，不再做子菜单（2026-11-27）

- **决策**：`manifests/config.yml` 的 `native.entries[]` 只保留一条命令
  `set hwdec d3d11va; script-message-to k7f_multi native <vf>:<k=v>…`（新增字段 `target`，缺省为 `k7f_multi`），
  去掉 `multi: […]` 与 2×–6× 的二级菜单。倍率由 `k7f_multi.lua` 应用：收到 `native` 消息后
  把当前倍数拼进 `playkit:multi=N:…`，一次 `vf set` 建链；全局未设定（`multi=nil`）时用
  `NATIVE_DEFAULT = 2`。`validate()` 对残留的 `multi` 字段直接 fail，`check()` 新增
「每条目的 `_native_command()` 必须出现在 `menu.conf`」的断言。
- **原因**：菜单里同时存在「倍数 (&M)」与原生滤镜的 2×– 6×，两处都要维护、
  容易不一致；而先按 6× 建链再改成 N× 会让 vf_playkit 初始化两次。现在倍率只有
  `k7f_multi.lua` 一个来源，且在同一条 `vf set` 里生效。原生滤镜没有“不指定”状态，
  `vf_playkit` 自带默认 6× 对 10 GB 卡太激进，所以未设定时取 2×。
- **边界 / 代价**：`k7f_multi.lua` 对 `playkit` 条目现在始终写 `multi`，不再“删键回到
  插件默认”；「清空」仍是 `vf clr playkit; set hwdec auto-copy`，不经过 `k7f_multi`。

## 39. 菜单段顺序与「VS 滤镜」改名（2026-11-27）

- **决策**：`menu.conf` 的播放相关段固定为「VS 滤镜 (&F) → 原生滤镜 (&P) → 着色器 (&G) → 倍数 (&M)」，
  内容仍是各自标记区生成；原「补帧参数 (&V)」段改名为「设置 (&V)」，从 VS 段附近挪到
  「工具 (&T)」与「关于 (&I)」之间（`input_uosc.conf` 的提示同步为 `#! 设置 > 补帧参数`，
  键位仍是 `V`）。原「VF 滤镜」统一改名「VS 滤镜」，`config.yml` 的 `vpypar.section`
  与 `build/config.py` 的提示文案、`check()` 报错文案同步。
- **原因**：四段都是「给播放链加/换处理」，相邻后菜单里从上到下就是
  VS 预设 → 原生滤镜 → 着色器 → 倍数 的处理顺序；「补帧参数」只是改正在跑的那条 vpy 的参数，
  属于设置而不是滤镜选择，放在工具区更符合入口语义。
- **边界 / 代价**：段顺序由 `portable_config/menu.conf` 基准文件与生成器的标记区共同决定，改顺序要
  同时改 `menu.conf`、`build/config.py` 的位置注释与 `manifests/config.yml` 的注释；隐藏标记
  （`hidden=true`）行必须留在各自段的首尾，否则 `check()` 的标记区校验会失败。运行期
  `menu-data` 里隐藏标记显示为 `state={"hidden"}` 的 submenu 项，属正常现象。

## 40. vs-mlrt 档移除，换成 vs-aji 完整版（2026-11-28）

- **决策**：删除 `manifests/packs/vs-mlrt.yml` 与 `sources.lock.json` 里全部 `vs-mlrt/*` 锁项，
  新增 `manifests/packs/vs-aji.yml`（`full: true`）。`vs-aji` = `vsdlssg` 的全部组件与预设
  （四个帧生成插件 DLL、四套引擎运行时）+ aji 运行时与模型，不是只含 aji 的独立档。
  `vsdlssg` 里原有的 `vsaji` 组件（`disable: true`）删除，避免两包各带一份。
- **原因**：aji 的 RIFE / 超分 / 时序是当前主推的 NV 路径，而 vs-mlrt 的 TensorRT-RTX 方案
  需要单独的 vsmlrt 插件、API4 移植轮子与六族模型，维护两套推理栈没有收益；用户要 aji 时
  也不该再为凑齐四颗帧生成引擎去跨包拷目录。合成一个完整版后，两个交付包是
  「默认档」与「默认档 + aji」，选包只按要不要 aji 决定。
- **边界 / 代价**：`vs-aji` 约 750 MB，比原 `vs-mlrt` 大；K7sfunc 的 `CUGAN_NV` /
  `DPIR_*_NV` / `ARTCNN_NV` / `RIFE_NV` / `DRBA_NV` 不再随包提供运行库与模型，
  需要用户自备。`vsaji` 组件资产来自 vsaji 仓库的 `scripts/make-release.py` 产物
  （zip 根下为 `aji/`，含依赖与 8 个模型），装到 `vs-plugins/aji/` 后再把
  `vsaji.dll` 复制到 `Lib/site-packages/vapoursynth/plugins/`。

## 41. aji 预设改由面板建链，不再直接写 vf 命令（2026-11-28）

- **决策**：`manifests/config.yml` 的 `aji_rife` / `aji_upscale` / `aji_tfix` / `aji_stack`
  统一只声明 `vpy: vs/MIX_AJI.vpy` 与 `panel_set`（`stages` / `framegen`），生成的菜单命令是
  `set hwdec auto-copy; vf set ""; script-message-to k7f_vpypar set …; script-message-to k7f_vpypar apply`，
  由面板统一写出唯一一条 `vapoursynth` 滤镜。`build/config.py` 新增 `_panel_command()`，
  预设去重键改为 `vpys + panel_set`。
- **原因**：mpv 的 `vf_vapoursynth` 同时只允许一个实例（销毁时断言
  `!p->in_node_active`，见 mpv-src `video/filter/vf_vapoursynth.c:582`），所以补帧 + 超分 +
  时序必须写进同一个 vpy（`MIX_AJI.vpy` 内部串联）。另外 vf 字符串形式无法携带带 `=` 的
  `user-data`（`--vf=vapoursynth=X:user-data=stages=fut` 必然解析失败），参数只能由 Lua 用
  `set_property_native('vf', …)` 传字典。
- **边界 / 代价**：菜单命令依赖 `k7f_vpypar` 脚本已加载；面板不认识的键会静默忽略，
  错误只在 mpv 日志里。预设本身不再自包含（`vf` 属性由面板书写），因此 `check()` 对 vpy
  数量与标记区的校验仍照旧。
