# mpv-playkit-pre

Windows x64 便携版 mpv **预览包**：配置来自 [hooke007/mpv_PlayKit](https://github.com/hooke007/mpv_PlayKit)，
播放器用**我们自行维护的构建**（[o5-null/mpv](https://github.com/o5-null/mpv)，带 `vf_playkit`
帧倍增滤镜），额外带上 VapourSynth 运行时，以及本仓库自己维护的
[K7sfunc fork](https://github.com/o5-null/K7sfunc)（在其上新增 `mod_playkit` 预设层与 `k7f_playkit` 前端）。

`pre` 是预览分支：**只追最新，不做兼容性保证**。组件版本随时可能跳到当天的最新构建，
出问题请对比 `BUILD_INFO.json` 里的版本组合。构建过程完全由 Python 脚本完成，产物是一个
解压即用的目录（不打安装器、不写注册表、不发布 release）。

## 包里有什么

| 路径 | 说明 | 来源 |
| --- | --- | --- |
| `mpv.exe` / `mpv.com` + 依赖 DLL | 播放器本体（动态链接，DLL 随包平铺；含 `vf_playkit`） | [o5-null/mpv](https://github.com/o5-null/mpv) release |
| `vs-plugins/vdlssg.dll` 等四个 DLL | 帧生成插件（DLSS-G / XeSS-FG / VFG / FSR4），引擎在 vsdlssg 档 | [o5-null/vs-framegen](https://github.com/o5-null/vs-framegen) |
| `yt-dlp.exe` | 在线播放后备（mpv 的 ytdl_hook 自动调用） | [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| `python.exe`、`Lib/`、`python3*.dll` | 官方嵌入式 CPython 3.15 | [python.org](https://www.python.org/downloads/windows/) |
| `vsscript.dll`、`libvapoursynth*.dll`、`Lib/site-packages/vapoursynth/` | 官方 VapourSynth R82 | [PyPI vapoursynth](https://pypi.org/project/VapourSynth/) |
| `portable.vs`、`vs-plugins/`、`vs-scripts/` | 便携标记与插件/脚本目录 | 本仓库 + wheel |
| `Lib/site-packages/vapoursynth/plugins/` | 10 个常用 VS 插件（akarin、mvtools、fmtconv、zsmooth、bm3d、bwdif、vivtc、tivtc、vszip、znedi3） | [PyPI vapoursynth-*](https://pypi.org/search/?q=vapoursynth) |
| `portable_config/` | 完整 mpv 配置、uosc 界面、脚本、shader、字体、lua | [hooke007/mpv_PlayKit](https://github.com/hooke007/mpv_PlayKit) |
| `Lib/site-packages/k7sfunc/` | 超分 / 插帧 / 降噪 / 去色带算法 + `mod_playkit` 预设层 | [o5-null/K7sfunc](https://github.com/o5-null/K7sfunc) 源码树 |
| `portable_config/scripts/k7f_playkit.lua` | 预设前端（OSD 提示 + 滤镜切换） | 同上 |
| `portable_config/scripts/k7f_vs.lua` | 首次运行写入 VSScript 的 Python 定位配置 | 同上 |
| `portable_config/script-opts/k7f_playkit.conf` | 前端默认参数 | 同上 |
| `licenses/`、`BUILD_INFO.json` | 许可文本与构建溯源 | 构建生成 |

## 快速开始

1. 解压 zip，进入 `mpv-playkit-pre-<版本>-windows-x64/`；
2. `mpv.exe` 直接播放。VapourSynth 链路不需要额外配置：`portable.vs` 与 `python*._pth` 已就位，
   `k7f_vs.lua` 会在首次运行时把 Python 定位写进 `%APPDATA%\vapoursynth\vapoursynth.toml`；
3. 想用预设，在你自己的 `input.conf` 里加一条绑定（脚本默认不占用任何按键）：

```conf
Ctrl+Shift+p  script-binding k7f_playkit/toggle
Ctrl+Shift+o  script-binding k7f_playkit/off
```

也可以改 `portable_config/script-opts/k7f_playkit.conf` 里的 `preset`，然后在控制台执行
`script-message-to k7f_playkit apply`。

> GPU 算法用的模型；`vsdlssg` 全量包不带，下 `vs-mlrt` 全量包后
> cugan / dpir 去块 / 通用超分 / ArtCNN / RIFE / DRBA 六族即可用。
> 默认的 `auto` 预设会按顺序逐级回退，缺模型只会降级并在 OSD 提示，不会黑屏。

## 两个全量包

不再有"基础包 + 补丁包"的叠加步骤：两个档位各自打成**完整、独立的包**，下哪一个就解压哪一个。

| 包 | 内容 | 体积 | 需要的硬件 |
| --- | --- | --- | --- |
| `...-windows-x64-vsdlssg.zip`（**默认档**） | 完整播放器 + 四个帧生成插件 DLL + DLSS-G 4.5 / XeSS-FG 的 NGX 引擎（含 sm86 解锁）；aji 插帧暂缓 | ~287 MB | NVIDIA RTX（帧生成建议 20/30 系以上） |
| `...-windows-x64-vs-mlrt.zip` | 完整播放器 + `vstrt_rtx` 插件（API4 移植）+ TensorRT-RTX 1.5 运行库 + cugan / dpir 去块模型 + 通用超分 / ArtCNN / RIFE / DRBA 模型 + onnx 等 Python 依赖 | ~1.1 GB | RTX 20 系及更新（Turing+），驱动 ≥ CUDA 12.9 |

- 两个包结构一致（`mpv.exe` + `portable_config/` + `Lib/` + `vs-plugins/` + `BUILD_INFO.json`），
  只有 `vs-plugins/` 与 `Lib/site-packages/vapoursynth/plugins/` 的内容不同；`PACK_INFO.json`
  记录了档位名与组件清单。
- 四个帧生成插件 DLL 在所有档位里都有（约 0.6 MB，落在 `vs-plugins/`，脚本首次使用时
  `LoadPlugin`）。
- `vs-mlrt` 自带 cugan、dpir 去块、通用超分、ArtCNN、RIFE、DRBA 六类模型，
  覆盖 K7sfunc 的 NV 算法；只有 dpir 的去噪两个（`drunet_gray` / `drunet_color`）需要自备：
  见 `docs/TOOLKIT.md`。


## 构建

```bash
pip install -r requirements.txt
python -m build ci         # 与 CI 同序：fetch -> assemble -> smoke -> package -> verify
```

产物在 `dist/out/mpv-playkit-pre-<版本>-windows-x64.zip`（附 `.sha256`）。只重建不下载时用
`python -m build all`（跳过 fetch）。分步执行：

```bash
python -m build fetch      # 下载并校验全部组件
python -m build assemble   # 装配 dist/stage/
python -m build smoke      # python/mpv/vapoursynth 冒烟测试
python -m build package    # 打确定性 zip
python -m build pack       # 打全部档位包（--name vsdlssg 只打一个）
python -m build verify --stage
python -m build verify --asset dist/out
```

### 三层结构（照 100pangci/mpv_PlayKit_TLS 的做法）

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 规则 | `manifests/components.yml` | 组件怎么装、装到哪、什么许可。很少改 |
| 版本 | `sources.lock.json` | 每个组件的 `version / url / sha256 / size`。换版本只动这里 |
| 指纹 | `build/inputs.py` | 对 build/manifests/lock 逐文件哈希，写进 `BUILD_INFO.json` |

换某个组件的版本：

```bash
python -m build.pin --id mpv --url <新资产直链>   # 下载→算哈希→写 lock
python -m build.pin --list                        # 看当前都钉了什么
python -m build.pin --check                       # 重新下载并校验全部
```

K7sfunc 用的是 GitHub 源码 tarball（`kind: git-tree`），所以换版本就是钉 fork 的新 commit：

```bash
python -m build.pin --id k7sfunc --version 1.9.0+pre.3 \
  --url https://codeload.github.com/o5-null/K7sfunc/tar.gz/<40位commit>
```

Python 与 VapourSynth 是两个独立组件（`--id python` / `--id vapoursynth`），钉的是
python.org 的 embed zip 与 PyPI 的 wheel 直链。

### 上游同步

`portable_config/` 与 `installer/` 是上游内容，由 `.github/workflows/sync-upstream.yml`
每天自动整目录替换，并把上游 commit 记在 `upstream.json`。

本仓库自己的东西全部放在 `build/`、`manifests/`、`.github/`，**不在上游目录里做任何修改**，
因此同步永远不会产生冲突。自定义功能不在这里实现——它们在 K7sfunc fork 里。

## 文档

- [`docs/BUILD.md`](docs/BUILD.md) —— 构建链细节、CI、可复现性
- [`docs/TOOLKIT.md`](docs/TOOLKIT.md) —— K7sfunc fork 的 `PLAYKIT_*`：预设、算子、如何加算法
- [`docs/DECISIONS.md`](docs/DECISIONS.md) —— 设计决策与已知坑：为什么这样分层、踩过哪些雷
- [`docs/upstream-README.md`](docs/upstream-README.md) —— 上游 mpv_PlayKit 原始说明

## 许可

本仓库新增代码（`build/`、`manifests/`、`.github/`）为 MIT；`portable_config/` 与
`installer/` 遵循上游 [LICENSE.MD](LICENSE.MD)；K7sfunc fork 为 GPL-3.0-or-later（`src/`）；
mpv 与 VapourSynth 分别是 GPL-2.0-or-later / LGPL-2.1-or-later。发行包内 `licenses/THIRD_PARTY.md`
列出了每个组件的实际版本与许可来源。
