# AGENTS.md

`mpv-playkit-pre`：构建 Windows x64 便携 mpv **预览包**（不是 mpv 本体，也不是配置仓库）。
产物是解压即用的目录 + 确定性 zip，只通过 GitHub Actions artifact 交付，**不发 release、不推 tag**。

## 目录职责

| 路径 | 说明 |
| --- | --- |
| `build/` | 打包链本体（本仓库唯一自己写的代码）：`__main__` 入口、fetch/assemble/smoke/package/verify/sync/pin、`pack.py` 打拓展包、`config.py` 按清单生成配置 |
| `manifests/components.yml` | 组件**规则**（kind / 装到哪 / exclude / paths / license），不含版本号 |
| `manifests/packs/*.yml` | 档位包的组件清单（`full: true` 为全量包，否则是补丁包）；版本同样进 lock，键是 `<pack>/<id>` |
| `manifests/config.yml` | **配置清单**：VF 预设表（按键 / vpy / 名称 / 依赖）+ 每个档位包启用哪几个预设 + `native` 原生滤镜段（menu.conf 里的独立块，目前只有 DLSS 帧生成），`build/config.py` 据此生成配置 |
| `sources.lock.json` | 组件**版本**（version / url / sha256 / size），唯一版本真相 |
| `configs/` | 本仓库的包布局文件（`portable.vs`、`vs-plugins.keep`、`configs/packs/` 下的许可与第三方说明） |
| `portable_config/` | **本地维护**的基准配置（取自 mpv-lazy 最后发版）；只有 `shaders/` 由 `build.sync` 跟随上游整目录替换 |
| `installer/` | 上游安装脚本，已冻结：不再同步、也不进包（保留只为留档）。例外：补帧滤镜跑分四件套（`mpv-FilterBench.bat` / `mpv-FilterBench.conf` / `mpv_filter_bench.lua` / `mpv_filter_bench_report.ps1`）由 `bench-scripts` 组件打进包的 `installer/` |
| `docs/` | `BUILD.md` 构建链、`DECISIONS.md` 决策与已知坑、`TOOLKIT.md` K7sfunc 预设层 |
| `.work/`、`dist/` | 临时解包与中间 stage，均已 gitignore；交付归档与下载缓存在共享目录（见下） |

## 共享产物（repos\）

本仓库与另外几个子仓库都在 `E:\code\dlssg-vfi\` 根下各自独立，**只有**构建产出的交付归档与
下载缓存放进根下的 `repos\`：

| 路径 | 说明 |
| --- | --- |
| `repos\dist\` | 交付归档（基础包、两个档位包、`*.sha256`、外部 release 资产副本）；`OUT_DIR` 默认指这里 |
| `repos\.cache\downloads\` | 下载缓存，所有子仓库共用一份；`DOWNLOAD_DIR` 默认指这里 |
| `<repo>\dist\stage\` | 中间 stage（单个 0.6–1.7 GB），留在仓库内 |

`build/common.py` 探测规则：`PLAYKIT_SHARED_ROOT` 显式指定优先；否则父目录下存在
`repos\dist` 或 `repos\.cache` 就用它（兼容旧布局 `<root>\repos\<repo>`）。
都不满足（CI checkout、仓库被单独拷走）时全部退回仓库内 `.work\downloads` / `dist\out`，
行为与旧版一致。`build/fetch.py` 在下载前还会看 `repos\dist` 里有没有同名且 sha256 一致的归档，
命中就硬链接进缓存——刚发过 release 的资产不必再下一次。

stage 在打包后**不会被删**：`ci` / `all` / `pack` 结束后 `dist\stage\<包名>` 原样留着，
可以直接跑里面的 `mpv.exe` 测试，不必先解 7z；同名重建时才清理旧目录，换提交哈希会换目录名，
旧的一直堆着，需要空间时手工删。

## 邻近仓库

本仓库在 `E:\code\dlssg-vfi\` 根下，旁边是同一套东西的源码，改 K7sfunc 功能时直接用：

- `..\k7sfunc` — K7sfunc 的 fork（PLAYKIT 预设、`RIFE_AJI` 等算子都在这里），push 后按 commit 钉进 `sources.lock.json`
- `..\vsaji` — aji 插帧引擎的 VS 插件与构建脚本，产物 `dist\aji\` 决定 `vs-plugins\aji\` 里放什么
- `..\k7sfunc-wiki`、`..\k7sfunc-wiki-pages`、`..\vs-framegen-wiki-pages` — 文档与静态页

改上游仓库不在本仓库提交；本仓库只留 manifest/lock 与文档。

## 命令

```bash
pip install -r requirements.txt        # 仅构建期需要 PyYAML
python -m build ci                     # 本地复现 CI：fetch→assemble→smoke→package→verify（合并前门槛）
python -m build all                    # 跳过 fetch，复用下载缓存
python -m build smoke                  # 冒烟：python import / mpv --version / vf=vapoursynth
python -m build verify --stage         # 校验 stage 结构/禁止项
python -m build verify --asset ..\dist\<zip>   # 归档默认落在共享 dist\
python -m build.pin --id <id> --url <url>   # 换版本唯一正确做法：下载→算 sha256→写 lock
python -m build config --stage <dir> --pack <pack>   # 只对已有 stage 重算配置（改清单后的快检）
python -m build.pin --list | --check | --dry-run
python -m build.sync [--check]         # 同步上游着色器目录；--check 有更新时退出码 3
python -m build pack [--name <pack>]   # 打拓展包（不带顶层目录的补丁归档，叠加到基础包根）
python -m build.pin --pack <pack> --id <id> --url <url>   # 拓展包组件的 pin（lock 键 <pack>/<id>）
```

没有单元测试、lint、typecheck；验证就等于 `smoke` + `verify`。完整构建会下载数百 MB
（缓存在 `repos\.cache\downloads`；CI 的 actions/cache 以 lock 哈希为 key）——用户没要求就别顺手跑 `ci`。

## 硬约束

1. **`portable_config/` 是本地维护的基准配置，不是上游镜像**。基准取自 mpv-lazy 最后发版的
   `portable_config`；只有 `portable_config/shaders/` 仍由 `build.sync` 整目录跟随上游
   （`installer/` 已冻结，不同步也不进包）。配置差异一律写进 `manifests/config.yml`：
   `presets` 定义 VS 预设（按键 / vpy / 名称 / 依赖），`packs` 定义每个档位包启用哪几个；
   `build/config.py` 会把 `input_uosc.conf` 与 `menu.conf` 的标记区重新生成，并裁掉未启用的
   `vs/*.vpy`。**不要手改两份文件标记区里的内容，也不要手写某个包专用的配置副本。**
   `native` 段生成 `menu.conf` 里紧跟"VS 滤镜"、在"着色器"之前的原生滤镜块（目前是 `playkit` 滤镜的
   DLSS 帧生成，倍率跟随「倍数」菜单），只有列出的档位包才出现——没有引擎的包宁可整段没有，也不留点不动的项。
   `packs.base` 是中间基础 stage 的配置（`assemble` / `smoke` / `verify` 不带 `--pack` 时用它），
   只放 mpv + k7sfunc 基础依赖就能跑的预设，不是交付物；用户拿到的是 `vsdlssg` / `vs-mlrt` 两个包。
   算法/前端功能仍写进 K7sfunc fork（`o5-null/K7sfunc`），本仓库只按 commit 钉它。
2. **不手改 `sources.lock.json`**，用 `build.pin`；`components.yml` 里不要出现版本号（规则/版本分离）。
3. **二进制不入库**：`.work/`、`dist/`、`*.7z`、`*.zip` 都在 gitignore；`portable_config/` 必须入库。
4. `git-tree` 组件（k7sfunc）按 `paths` 白名单复制——fork 里新增的文件要同步加映射才会进包。
5. CI 不在 push 触发（schedule / workflow_dispatch / pull_request），push 不会替你验证。
6. **档位包分两种形态**：`full: true` 是全量包（自带基础包，产物同构于基础包 zip，当前两个档位
   vsdlssg / vs-mlrt 都是这种）；不带 `full` 的补丁包只许放 `Lib/site-packages/vapoursynth/plugins/**`、
   `Lib/site-packages/` 下的纯 Python 包（补丁包自己的运行依赖，如 onnx/numpy）、
   `vs-plugins/**`、`portable_config/**`、`PACK_INFO.json`（配置不同就放进补丁包，解压直接覆盖）；
   补丁包禁止 `mpv.exe`、`python.exe`、`vsscript.dll`、`vapoursynth.pyd`、`k7sfunc/`、`vapoursynth/` 本体等——覆盖式解压写错就毁基础包。

## 容易踩的坑

- `vf=vapoursynth` 的滤镜参数用 `:` 分隔，Windows 盘符会被当成分隔符：用相对路径（smoke 的做法）。
- VS R82 起 `vsscript.dll` 不再链接 Python，靠随包 `k7f_vs.lua` 写
  `%APPDATA%\vapoursynth\vapoursynth.toml`；键必须是整条小写路径，反斜杠要转义成 `\\`。
- 非 UTF-8 控制台会炸中文日志：`build/common.py` 导入时切 UTF-8，CI 另设 `PYTHONUTF8=1`。
- codeload 走代理时 urllib 会握手中断，`fetch.py` 三次失败后回退 `curl -x $HTTPS_PROXY`。
- 解 7z 依赖 7-Zip / `SEVEN_Z` / Windows 自带 `tar.exe`，没有就报 `找不到 7z 或 bsdtar`。
- `.gitignore` 不支持行尾注释；`core.autocrlf` 必须保持 `false`，否则 `build sync` 后出现几百个假修改。
- 缺模型/插件时 `PLAYKIT_*` 只降级并在 OSD 提示，不算 bug；`mpv.conf` 里空值选项的报错属于噪声，见 `build/smoke.py` 的 `NON_FATAL`。
- 配置清单里"未启用"的预设不是删掉，但也不是写成 `#` 注释：`select.lua` 不认注释，每行都会变成菜单项。`menu.conf` 里未启用的预设保留命令并加 `disabled=true`（灰显不可点，标题写明缺什么），标记行加 `hidden=true`；`input_uosc.conf` 是按键表，注释安全，才用 `#`。vpy 会被真正裁掉。新增预设要同时想清楚 `requires` 写什么。
- 原生滤镜（`playkit`）只吃 D3D11 硬件帧：`hwdec=auto-copy` 时它静默直通（没有 2×、也不报错），所以清单生成的命令是 `set hwdec d3d11va; vf set playkit:...`；反过来 VS 预设命令带 `set hwdec auto-copy` 前缀，避免用过原生滤镜后 `vf=vapoursynth` 吃到 D3D11 帧。
- VS 插件只有放 `Lib/site-packages/vapoursynth/plugins/`（含子目录）才会被自动加载；`vs-plugins/` 里放 DLL 不生效。
- VS R80 起不支持 API 3 插件：`vs-mlrt` 官方二进制全是 API 3，R82 直接拒绝，要用 API4 移植轮子（见 DECISIONS 第 11 条）。
- 版本号 = `VERSION` + 提交短哈希，CI 可用 `PLAYKIT_VERSION` 覆盖；产物名统一带 `pre`（预览分支不保证兼容）。

## 约定

- 文档、注释、提交信息用中文；提交信息按 `type(scope): 摘要`（如 `fix(package): …`）。
- 改设计前先读 `docs/DECISIONS.md`，新决策追加条目并写清"原因/代价"，不要改写既有理由。
