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

## 已知坑

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
