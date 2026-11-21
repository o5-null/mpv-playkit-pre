# K7sfunc fork 的 PLAYKIT 扩展

自定义功能**不在本仓库**，而在 [o5-null/K7sfunc](https://github.com/o5-null/K7sfunc)（本仓库的
K7sfunc fork）里：`src/k7sfunc/mod_playkit.py` 提供一个**有名字、会降级、有日志**的预设层，
`mpv/portable_config/scripts/k7f_playkit.lua` 是它的 mpv 前端。

上游 [LumeCraft-Labs/K7sfunc](https://github.com/LumeCraft-Labs/K7sfunc) 只提供一堆算法函数
（`ACNET_STD`、`RIFE_NV`、`NLM_STD` …），每个都要自己写 vpy、自己处理失败。`mod_playkit`
把它们包成 8 个预设和一个入口 `PLAYKIT_RUN`，mpv 里"一键开启"就成了一条命令。

这样分工的原因：算法层和前端都是 K7sfunc 的一部分，跟着它的代码演进、共用它的版本号；
本仓库只负责"把哪一份 K7sfunc、装进哪个包"。

## 包里的位置

```
mpv-playkit-pre-<ver>-windows-x64/
├─ python315._pth                        # python315.zip / . / Lib\site-packages / import site
├─ python.exe / python3.dll              # 官方嵌入式 CPython
├─ vsscript.dll / libvapoursynth*.dll    # 官方 VapourSynth 运行时（包根副本）
├─ Lib/site-packages/vapoursynth/        # wheel 本体 + vs-plugins/vs-scripts
├─ Lib/site-packages/k7sfunc/
│   ├─ __init__.py                       # 1.9.0+pre.N，导出上游全部函数 + PLAYKIT_*
│   ├─ mod_playkit.py                    # ★ 预设层
│   └─ mod_scale/mod_memc/mod_dbdn/...   # 上游算法
└─ portable_config/
    ├─ scripts/k7f_vs.lua                # 写入 VSScript 的 Python 定位配置
    ├─ scripts/k7f_playkit.lua           # ★ mpv 前端
    └─ script-opts/k7f_playkit.conf      # 默认参数
```

装配时 `Lib/site-packages/k7sfunc/` 是**直接复制 fork 的 `src/k7sfunc` 源码树**（不是 wheel），
所以改 fork 的 Python 代码只需要重新钉一次 commit、重建包，不用在 CI 里跑 pip install。

## 在 mpv 里怎么用

**1. lua 前端（推荐）** —— `k7f_playkit.lua`

在 `input.conf` 里绑键（默认不抢按键，和 mpv_PlayKit 其它脚本一致）：

```conf
Ctrl+Shift+p  script-binding k7f_playkit/toggle
Ctrl+Shift+o  script-binding k7f_playkit/off
```

行为：读 `portable_config/script-opts/k7f_playkit.conf`，生成 `~~/k7f_playkit.vpy`，
再挂成 `@PLAYKIT:vapoursynth=` 滤镜；再按一次移除（不中断播放）。

也可以用脚本消息（控制台或 input.conf）：

```conf
script-message-to k7f_playkit apply
script-message-to k7f_playkit off
script-message-to k7f_playkit status
script-message-to k7f_playkit set-preset anime
script-message-to k7f_playkit set-key engine acnet
```

**2. 直接挂 vpy** —— 自己写三行，走同一套预设：

```conf
Ctrl+1  vf toggle vapoursynth="~~/my_upscale.vpy"
```

```python
from k7sfunc import PLAYKIT_RUN
PLAYKIT_RUN(video_in, preset="upscale", target_h=1440, fps_in=container_fps)
```

**3. 只用算子** —— `PLAYKIT_UPSCALE / PLAYKIT_MEMC / PLAYKIT_DENOISE / PLAYKIT_DEBAND`
可以单独调用，组合由你自己定。

## 预设（`PLAYKIT_PRESETS`）

| 预设 | 做什么 | 主要算子 |
| --- | --- | --- |
| `auto` | 只在源分辨率低于 `target_h` 时超分 | 同 `upscale` |
| `upscale` | 超分到 `target_h`，引擎逐级回退 | ARTCNN_NV → ACNET_STD → CUGAN_NV → EDI_US_STD |
| `memc` | 插帧到 `memc_fps` | RIFE_NV → RIFE_DML → 保持原帧率 |
| `denoise` | 轻度降噪 | NLM_STD（`nr_lv`） |
| `deband` | 去色带 | DEBAND_STD（`bdy_rth`） |
| `clean` | 去色带 + 降噪 | DEBAND_STD + NLM_STD |
| `anime` | 动画向：超分 + 去色带 | ACNET_STD + DEBAND_STD |
| `live` | 实拍向：降噪 + 插帧 | NLM_STD + RIFE |

**降级是设计的一部分。** 缺模型、缺插件、显存不够时不会抛到 mpv 里变成黑屏，
而是打一行 `[playkit] 警告: 超分引擎 artcnn 不可用: ...` 再试下一个，最后兜底
`core.resize.Lanczos`。这一点在无 GPU 的 CI 上尤其重要（冒烟测试就跑在这种环境）。

## 接口（`mod_playkit.py`）

唯一入口：

```python
PLAYKIT_RUN(input, preset="auto", target_h=0, engine="auto", memc_engine="auto",
            memc_fps=60.0, fps_in=None, denoise_lv=3.0, deband_rth=48.0,
            gpu=0, gpu_m=1, gpu_t=2)
```

`target_h=0` 且 `preset="auto"` 时不做任何处理。`engine` 取
`artcnn/acnet/cugan/edi/ngu/none`，`memc_engine` 取 `rife_nv/aji/rife_dml/none`。
`auto` 按 `rife_nv → aji → rife_dml → none` 降级；`aji` 只支持整数倍率（24→48 可以，
24→60 这种 5/2 会报错后继续降级）。

分步调用：

| 函数 | 参数 | 调用的上游函数 |
| --- | --- | --- |
| `PLAYKIT_UPSCALE(clip, target_h, engine, gpu, gpu_m)` | engine: `artcnn/acnet/cugan/edi/ngu/none` | `ARTCNN_NV(model=8)` / `ACNET_STD(model=1)` / `CUGAN_NV(nr_lv=-1)` / `EDI_US_STD(cpu=True)` / `NGU_HQ()` |
| `PLAYKIT_MEMC(clip, fps_in, fps_out, engine, gpu, gpu_t)` | engine: `rife_nv/aji/rife_dml/none` | `RIFE_NV` / `RIFE_AJI` / `RIFE_DML`，帧率比用 `Fraction` 求最简整数比；aji 要求整数倍 |
| `PLAYKIT_DENOISE(clip, nr_lv, gpu)` | 默认 3.0 | `NLM_STD(nr_lv=...)` |
| `PLAYKIT_DEBAND(clip, bdy_rth)` | 默认 48.0 | `DEBAND_STD(bdy_rth=...)` |
| `PLAYKIT_FIT(clip, target_h)` | — | `core.resize.Lanczos` |

超分算子统一在最后做一次 `PLAYKIT_FIT`，所以 `target_h` 一定被精确满足，
不会因为某个模型只支持 2x/4x 而给出奇怪的高度。

## 加自己的算子

在 fork 的 `src/k7sfunc/mod_playkit.py` 里加，保持 K7sfunc 的代码风格（tab 缩进、
`_validate_*` 校验、模块内不打日志），然后：

1. **算子**：写一个私有 helper，例如

```python
def _playkit_sharp(input : vs.VideoNode, amount : float = 0.5) -> vs.VideoNode :
	return CCD_STD(input, strength=amount)   # 参数按 K7sfunc 文档填
```

2. **挂进预设**：在 `PLAYKIT_*` 对应的分支里调用，用 `try/except` 包住并
   `_playkit_warn("...", exc)` 降级。
3. **导出**：新公开函数加进 `__all__`；新预设加进 `PLAYKIT_PRESETS`，
   前端 `k7f_playkit.conf` 的注释也同步一下。
4. **发版**：`__version__` 递增（`1.9.0+pre.N`），push 到 fork，然后在本仓库
   `python -m build.pin --id k7sfunc --url https://codeload.github.com/o5-null/K7sfunc/tar.gz/<新commit>`。

## 模型与插件放哪

K7sfunc 的模型和 GPU 组件不在源码里。分三种情况：

- **基础包自带**：`akarin`/`mvtools`/`fmtconv`/`zsmooth`/`bm3d`/`bwdif`/`vivtc`/`tivtc`/
  `vszip`/`znedi3` 这 10 个插件（来自 PyPI 的 API 4 轮子），落在
  `Lib/site-packages/vapoursynth/plugins/`，开箱即可用。
- **`tensorrt-rtx` 包自带**：`vstrt_rtx.dll` + TensorRT-RTX 运行库 + 六族模型 + `onnx` 等
  Python 依赖，装完 `CUGAN_NV` / `ARTCNN_NV` / `RIFE_NV` / `DRBA_NV` / `DPIR_DBLK_NV`
  即可出帧（缺模型时 K7sfunc 会报"所请求的模型缺失"，不会黑屏）：

```
Lib/site-packages/vapoursynth/plugins/vsmlrt/
├─ cugan/            cugan 3 个（pro-* / conservative 各 up2x）
├─ dpir/             drunet deblocking 2 个（DPIR_DBLK_NV 的 model 2/3）
├─ ArtCNN/           ArtCNN_R16F96 / R8F64 / R8F64_DS
├─ rife/             RIFE 4.25 lite / 4.26 / 4.26 heavy / 4.6 / 4.6 ensemble
├─ rife_v2/          同一组 RIFE（TRT 路径用这个目录）
├─ drba/             distilDRBA v1 / v2_lite 四变体，fp32 与 fp16 各一套
└─ *.onnx            5 个通用超分模型（HFA2kCompact / Ani4Kv2 / AnimeJaNai / Anime1080Fixer）
```

- **仍需自己放**：DPIR 去噪用的 `drunet_gray` / `drunet_color`（`dpir/` 目录，来自
  `hooke007/dotfiles` 的 `mpv_addones`），以及 NGU 的 `madVR64.ax`：

```
Lib/site-packages/vapoursynth/plugins/vsmlrt/models/dpir/   # 可选：去噪模型
vs-plugins/madVR/madVR64.ax                                 # NGU 相关
```

- **vsaji（aji 插帧引擎）**：插件与运行时分开放，`rife_aji.dll` 进插件目录由 VS 自动加载，
  其余是插件运行期 dlopen 的资源：

```
Lib/site-packages/vapoursynth/plugins/rife_aji.dll
vs-plugins/aji/
├─ aji.dll  aji_trt.dll  cudart64_13.dll  aji-runtime.json
├─ trt/nvinfer_11.dll  trt/cudart64_13.dll   # 精简 TensorRT 运行时（必须完整，lean 只能建 IRuntime）
├─ conf/rife_only_414.conf
└─ rife/rife_v4.14.onnx
```

  即 vsaji 的 `dist/aji/` 整个目录给 `vs-plugins/aji/`，再把它的 `rife_aji.dll` 单独丢进插件目录。
  `PLAYKIT_MEMC` 按插件自报的目录、同级/上级 `aji/`、`<包根>/vs-plugins/aji` 依次探测，
  另可用环境变量 `AJI_PLUGIN`（DLL 路径）、`AJI_DIR`（运行时目录）指定。

其余模型的来源是 <https://github.com/hooke007/dotfiles/releases/tag/mpv_addones> 里的
`vs-k7sfunc.*` 资产（`rife_std-core`、`mad.b208` 等）。包里那五族是从那份资产里挑出来的，
另外也单独发在本仓库的 Release（tag `models-v1`，一族一个 zip），想只补某一族就从那里下。

## 拓展包与它的两个目录

基础包里没有帧生成插件，也没有 TensorRT 推理插件——它们由补丁包（`manifests/packs/*.yml`）
以 overlay zip 的形式叠加到包根。补丁包落地时**只碰两个位置**：

```
Lib/site-packages/vapoursynth/plugins/   # 插件 DLL，由 VapourSynth 自动加载（含子目录）
└─ vsmlrt/                               # tensorrt-rtx 包：vstrt_rtx.dll + vsmlrt-cuda/ 运行库
vs-plugins/                              # 资源：模型、引擎包、madVR
└─ bin/
   ├─ dlss45/                            # DLSS-G 的 NGX 引擎包（MEMC_DLSSG_NV.vpy 按此路径找）
   └─ xessfg/                            # XeSS-FG 的引擎包
```

区别是**机制不同、不能合并**：

- `plugins/` 是 VapourSynth 自己的插件目录，进程启动时扫描并 `LoadPlugin`；放在 `vs-plugins/`
  里不会被自动加载（`VAPOURSYNTH_PLUGIN_PATH` 也不是它认的变量）。
- 引擎包与模型是**插件运行时按相对路径查的文件**，不是可加载模块。例如 DLSS-G 的代理在
  `<插件目录>\dlss45` 找引擎；`MEMC_DLSSG_NV.vpy` 因此按 `vs-plugins/bin/dlss45` 探测，
  再通过 `proxy_dir` 参数指过去。

`vstrt_rtx.dll` 的 TRT 运行库必须与它同级放在 `vsmlrt-cuda/` 子目录里：插件用
`dllDir()/vsmlrt-cuda/tensorrt_rtx_<主>_<次>.dll` 做延迟加载预取，放别处只会在第一次推理时
报找不到 DLL。

想确认补丁包生效（不用开 mpv）：

```powershell
./python -c "import vapoursynth as vs; print(vs.__version__, [n for n in ('vdlssg','vxessfg','vvfg','vfsr4','trt_rtx') if hasattr(vs.core, n)])"
```


## 调试

- 日志前缀固定 `[playkit]`，`mpv --msg-level=all=v` 或看 `~~/k7f_playkit.vpy`（前端生成的 vpy）；
- `script-message-to k7f_playkit status` 打印当前预设与滤镜是否启用；
- 确认 K7sfunc 与扩展都在：
  `./python -c "import k7sfunc; print(k7sfunc.__version__, hasattr(k7sfunc,'PLAYKIT_RUN'))"`；
- 确认 VapourSynth 链路：`./python -c "import vapoursynth as vs; print(vs.core.version())"`。
- mpv 里报 `Failed to initialize VapourSynth VSScript library` 时，先看
  `%APPDATA%\vapoursynth\vapoursynth.toml` 是否有一行指向**本包**的 `vsscript.dll`（小写全路径）。
  `k7f_vs.lua` 首次运行会自动写；包被挪到新位置后它会重写，同时清理指向已消失目录的旧行。
