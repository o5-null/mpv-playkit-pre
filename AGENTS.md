# AGENTS.md

`mpv-playkit-pre`：构建 Windows x64 便携 mpv **预览包**（不是 mpv 本体，也不是配置仓库）。
产物是解压即用的目录 + 确定性 zip，只通过 GitHub Actions artifact 交付，**不发 release、不推 tag**。

## 目录职责

| 路径 | 说明 |
| --- | --- |
| `build/` | 打包链本体（本仓库唯一自己写的代码）：`__main__` 入口、fetch/assemble/smoke/package/verify/sync/pin、`pack.py` 打拓展包 |
| `manifests/components.yml` | 组件**规则**（kind / 装到哪 / exclude / paths / license），不含版本号 |
| `manifests/packs/*.yml` | 拓展包（挡位补丁包）的组件清单；版本同样进 lock，键是 `<pack>/<id>` |
| `sources.lock.json` | 组件**版本**（version / url / sha256 / size），唯一版本真相 |
| `configs/` | 本仓库的包布局文件（`portable.vs`、`vs-plugins.keep`、`configs/packs/` 下的许可与第三方说明） |
| `portable_config/`、`installer/` | **上游** hooke007/mpv_PlayKit 内容，每日整目录覆盖 |
| `docs/` | `BUILD.md` 构建链、`DECISIONS.md` 决策与已知坑、`TOOLKIT.md` K7sfunc 预设层 |
| `.work/`、`dist/` | 下载缓存与构建产物，均已 gitignore |

## 邻近仓库

本仓库在 `E:\code\dlssg-vfi\` 下，旁边是同一套东西的源码，改 K7sfunc 功能时直接用：

- `..\k7sfunc` — K7sfunc 的 fork（PLAYKIT 预设、`RIFE_AJI` 等算子都在这里），push 后按 commit 钉进 `sources.lock.json`
- `..\vsaji` — aji 插帧引擎的 VS 插件与构建脚本，产物 `dist\aji\` 决定 `vs-plugins\aji\` 里放什么
- `..\k7sfunc-wiki`、`..\k7sfunc-wiki-pages`、`..\vs-framegen-wiki-pages` — 文档与静态页

改上游仓库不在本仓库提交；本仓库只留 manifest/lock 与文档。

## 命令

```bash
pip install -r requirements.txt        # 仅构建期需要 PyYAML
python -m build ci                     # 本地复现 CI：fetch→assemble→smoke→package→verify（合并前门槛）
python -m build all                    # 跳过 fetch，复用 .work/downloads 缓存
python -m build smoke                  # 冒烟：python import / mpv --version / vf=vapoursynth
python -m build verify --stage         # 校验 stage 结构/禁止项
python -m build verify --asset dist/out/<zip>
python -m build.pin --id <id> --url <url>   # 换版本唯一正确做法：下载→算 sha256→写 lock
python -m build.pin --list | --check | --dry-run
python -m build.sync [--check]         # 同步上游两目录；--check 有更新时退出码 3
python -m build pack [--name <pack>]   # 打拓展包（overlay zip，叠加到基础包根）
python -m build.pin --pack <pack> --id <id> --url <url>   # 拓展包组件的 pin（lock 键 <pack>/<id>）
```

没有单元测试、lint、typecheck；验证就等于 `smoke` + `verify`。完整构建会下载数百 MB
（缓存于 `.work/downloads`；CI 的 actions/cache 以 lock 哈希为 key）——用户没要求就别顺手跑 `ci`。

## 硬约束

1. **不改 `portable_config/` 与 `installer/`**。同步是整目录替换，往里加文件也会被删掉；
   自定义功能一律写进 K7sfunc fork（`o5-null/K7sfunc`），本仓库只按 commit 钉它。
2. **不手改 `sources.lock.json`**，用 `build.pin`；`components.yml` 里不要出现版本号（规则/版本分离）。
3. **二进制不入库**：`.work/`、`dist/`、`*.7z`、`*.zip` 都在 gitignore；`portable_config/` 必须入库。
4. `git-tree` 组件（k7sfunc）按 `paths` 白名单复制——fork 里新增的文件要同步加映射才会进包。
5. CI 不在 push 触发（schedule / workflow_dispatch / pull_request），push 不会替你验证。
6. **拓展包可覆盖配置，但不得含基础包运行时本体**：允许 `Lib/site-packages/vapoursynth/plugins/**`、
   `Lib/site-packages/` 下的纯 Python 包（补丁包自己的运行依赖，如 onnx/numpy）、
   `vs-plugins/**`、`portable_config/**`、`PACK_INFO.json`（配置不同就放进补丁包，解压直接覆盖）；
   禁止 `mpv.exe`、`python.exe`、`vsscript.dll`、`vapoursynth.pyd`、`k7sfunc/`、`vapoursynth/` 本体等——覆盖式解压写错就毁基础包。

## 容易踩的坑

- `vf=vapoursynth` 的滤镜参数用 `:` 分隔，Windows 盘符会被当成分隔符：用相对路径（smoke 的做法）。
- VS R82 起 `vsscript.dll` 不再链接 Python，靠随包 `k7f_vs.lua` 写
  `%APPDATA%\vapoursynth\vapoursynth.toml`；键必须是整条小写路径，反斜杠要转义成 `\\`。
- 非 UTF-8 控制台会炸中文日志：`build/common.py` 导入时切 UTF-8，CI 另设 `PYTHONUTF8=1`。
- codeload 走代理时 urllib 会握手中断，`fetch.py` 三次失败后回退 `curl -x $HTTPS_PROXY`。
- 解 7z 依赖 7-Zip / `SEVEN_Z` / Windows 自带 `tar.exe`，没有就报 `找不到 7z 或 bsdtar`。
- `.gitignore` 不支持行尾注释；`core.autocrlf` 必须保持 `false`，否则 `build sync` 后出现几百个假修改。
- 缺模型/插件时 `PLAYKIT_*` 只降级并在 OSD 提示，不算 bug；`mpv.conf` 里上游的空值选项报错属于噪声，见 `build/smoke.py` 的 `NON_FATAL`。
- VS 插件只有放 `Lib/site-packages/vapoursynth/plugins/`（含子目录）才会被自动加载；`vs-plugins/` 里放 DLL 不生效。
- VS R80 起不支持 API 3 插件：`vs-mlrt` 官方二进制全是 API 3，R82 直接拒绝，要用 API4 移植轮子（见 DECISIONS 第 11 条）。
- 版本号 = `VERSION` + 提交短哈希，CI 可用 `PLAYKIT_VERSION` 覆盖；产物名统一带 `pre`（预览分支不保证兼容）。

## 约定

- 文档、注释、提交信息用中文；提交信息按 `type(scope): 摘要`（如 `fix(package): …`）。
- 改设计前先读 `docs/DECISIONS.md`，新决策追加条目并写清"原因/代价"，不要改写既有理由。
