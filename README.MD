# mpv-playkit-pre

Windows x64 便携版 mpv **预览包**：配置来自 [hooke007/mpv_PlayKit](https://github.com/hooke007/mpv_PlayKit)，
播放器用**我们自行维护的构建**（[o5-null/mpv](https://github.com/o5-null/mpv)，带 `vf_playkit`
帧倍增滤镜），额外带上 VapourSynth 运行时，以及本仓库自己维护的
[K7sfunc fork](https://github.com/o5-null/K7sfunc)（在其上新增 `mod_playkit` 预设层与 `k7f_playkit` 前端）。

目标是实现稳定和最新的前沿技术体验
添加更高速的实时视频处理功能


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

1. 解压 7z（7-Zip 或兼容工具），进入 `mpv-playkit-pre-<版本>-windows-x64/`；
2. `mpv.exe` 直接播放。installer文件夹中提供了直接设为媒体文件默认打开方式的脚本

> GPU 算法用的模型；`vsdlssg` 全量包自带4个vs插件和1个原生滤镜，`vs-aji` 再加 aji 运行时与模型

## 两个全量包

不再有"基础包 + 补丁包"的叠加步骤：两个档位各自打成**完整、独立的包**，下哪一个就解压哪一个。

| 包 | 内容 | 体积 | 需要的硬件 |
| --- | --- | --- | --- |
| `...-windows-x64-vsdlssg.7z`（**默认档**） | 完整播放器 + 四个帧生成插件 DLL + DLSS-G 4.5 / XeSS-FG / NVIDIA VFG / FSR-FG 四套引擎运行时（含 sm86 解锁） | ~338 MB | NVIDIA RTX（帧生成建议 20/30 系以上） |
| `...-windows-x64-vs-aji.7z`（**完整版**） | 完整播放器 + 四个帧生成插件 DLL 与四套引擎运行时（即 vsdlssg 档的全部内容）+ aji（AnimeJaNai libaji）插件：RIFE 补帧 / 2× 超分 / 时序处理 / 三层叠加，包内自带 TensorRT / TensorRT-RTX 运行库与 8 个超分 / 时序模型 | ~510 MB | NVIDIA RTX（aji 建议 20/30 系以上） |

> 包是 `7z`（最高压缩率 LZMA2），需要 [7-Zip](https://www.7-zip.org/) 或兼容工具解压；
> 解压后是 `mpv-playkit-pre-<版本>-windows-x64/` 这一个目录。

- 两个包结构一致（`mpv.exe` + `portable_config/` + `Lib/` + `vs-plugins/` + `BUILD_INFO.json`），
  `vs-aji` 在 `vsdlssg` 的基础上多出 `vs-plugins/aji/` 与插件目录里的 `vsaji.dll`；
  `PACK_INFO.json` 记录了档位名与组件清单。
- 四个帧生成插件 DLL 在所有档位里都有（约 0.6 MB，落在 `vs-plugins/`，脚本首次使用时
  `LoadPlugin`）。
- `vs-aji` 自带 aji 运行时（`aji.dll` / `aji_trt.dll` / `aji_trtrtx.dll` + TensorRT 与
  TensorRT-RTX 运行库）和 8 个模型：RIFE 4.14、4 个 AnimeJaNai 超分、3 个 temporalfix，
  补帧 / 超分 / 时序都不用另下。原来的 `vs-mlrt` 档（vsmlrt 的 NV 算法与六族模型）已不再提供。


## 构建

```bash
pip install -r requirements.txt
python -m build ci         # 与 CI 同序：fetch -> assemble -> smoke -> package -> verify
```

产物在 `dist/out/mpv-playkit-pre-<版本>-windows-x64.7z`（附 `.sha256`；`--format zip` 出旧格式）。只重建不下载时用
`python -m build all`（跳过 fetch）。分步执行：

```bash
python -m build fetch      # 下载并校验全部组件
python -m build assemble   # 装配 dist/stage/
python -m build smoke      # python/mpv/vapoursynth 冒烟测试
python -m build package    # 出 7z（--format zip 出确定性 zip）
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
