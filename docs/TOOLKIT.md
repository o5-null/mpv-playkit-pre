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
├─ python314._pth                        # python314.zip / . / vs-scripts / import site
├─ Lib/site-packages/k7sfunc/
│   ├─ __init__.py                       # 1.9.0+pre.N，导出上游全部函数 + PLAYKIT_*
│   ├─ mod_playkit.py                    # ★ 预设层
│   └─ mod_scale/mod_memc/mod_dbdn/...   # 上游算法
└─ portable_config/
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
`artcnn/acnet/cugan/edi/ngu/none`，`memc_engine` 取 `rife_nv/rife_dml/none`。

分步调用：

| 函数 | 参数 | 调用的上游函数 |
| --- | --- | --- |
| `PLAYKIT_UPSCALE(clip, target_h, engine, gpu, gpu_m)` | engine: `artcnn/acnet/cugan/edi/ngu/none` | `ARTCNN_NV(model=8)` / `ACNET_STD(model=1)` / `CUGAN_NV(nr_lv=-1)` / `EDI_US_STD(cpu=True)` / `NGU_HQ()` |
| `PLAYKIT_MEMC(clip, fps_in, fps_out, engine, gpu, gpu_t)` | — | `RIFE_NV` / `RIFE_DML`，帧率比用 `Fraction` 求最简整数比 |
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

K7sfunc 的模型和 GPU 组件不在源码里，按它文档的约定放在 mpv 根目录：

```
vs-plugins/models/              # 各种 .onnx 模型（ACNet / RIFE / DPIR ...）
vs-plugins/madVR/madVR64.ax     # NGU 相关
vs-plugins/librife_windows_x86-64.dll
```

来源是 <https://github.com/hooke007/dotfiles/releases/tag/mpv_addones> 里的
`vs-k7sfunc.*` 资产。**本仓库不打包这些资产**（单个就上百 MB，且与算法版本强绑定），
需要时自行下载解压到上面的路径。

## 调试

- 日志前缀固定 `[playkit]`，`mpv --msg-level=all=v` 或看 `~~/k7f_playkit.vpy`（前端生成的 vpy）；
- `script-message-to k7f_playkit status` 打印当前预设与滤镜是否启用；
- 确认 K7sfunc 与扩展都在：
  `./python -c "import k7sfunc; print(k7sfunc.__version__, hasattr(k7sfunc,'PLAYKIT_RUN'))"`；
- 确认 VapourSynth 链路：`./python -c "import vapoursynth as vs; print(vs.core.version())"`。
