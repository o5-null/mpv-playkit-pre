# 第三方组件与许可（tensorrt-rtx 补丁包）

本补丁包不含任何 NVIDIA 专有引擎或模型权重，只提供运行库与开源插件；把 zip
解压到基础包根后，下列文件会出现在 `Lib/site-packages/vapoursynth/plugins/vsmlrt/`
与 `vs-plugins/tensorrt-rtx/` 下。

## 组件清单

| 文件 | 来源 | 许可 |
| --- | --- | --- |
| `vapoursynth/plugins/vsmlrt/vstrt_rtx.dll` | [AliceTeaParty/vapoursynth-api4-wheels](https://github.com/AliceTeaParty/vapoursynth-api4-wheels) 的 `vs-trt-rtx-cu129`（上游 vs-mlrt 源码 revision `761a313`，改写为 VapourSynth API 4 后重编译） | GPL-3.0-or-later |
| `vapoursynth/plugins/vsmlrt/vsmlrt-cuda/tensorrt_rtx_1_5.dll` | NVIDIA TensorRT-RTX 1.5 运行库（同仓 `vs-tensorrt-rtx-cu129`） | NVIDIA TensorRT License Agreement |
| `vapoursynth/plugins/vsmlrt/vsmlrt-cuda/tensorrt_onnxparser_rtx_1_5.dll` | 同上 | NVIDIA TensorRT License Agreement |
| `vapoursynth/plugins/vsmlrt/vsmlrt-cuda/tensorrt_rtx.exe` | 同上（TRT-RTX 的引擎构建器） | NVIDIA TensorRT License Agreement |

许可原文见同目录 `LICENSE.txt`（NVIDIA）与基础包 `licenses/`（vs-mlrt 侧）。
NVIDIA 运行库按《NVIDIA TensorRT License Agreement》随分发物附带许可即允许再分发；
本包**不**包含 TensorRT SDK、头文件或样例。

## 为什么不是官方 vs-mlrt 二进制

VapourSynth R80 起移除 API 3，官方 vs-mlrt（含最新的 `v16.4.test1`）全系仍按 API 3
编译，在 R82 上会被拒绝加载（`uses API 3, which is no longer supported`）；
上游维护者在 [AmusementClub/vs-mlrt#171](https://github.com/AmusementClub/vs-mlrt/issues/171)
中明确表示不迁移。上面这组轮子是把上游源码 vendored 进镜像仓、改写为 API 4 后
重编译的产物，`core.trt_rtx` 的函数面与调用签名与上游一致，K7sfunc 侧脚本无需改动。

## 版本锁定说明

插件与运行库同属 `16.2.2+alice.1` 一次发布（对应上游 vs-mlrt `v16.2.6` 的 API 4 移植），
二者必须成对更新：TRT-RTX 1.5 的运行库名是 `tensorrt_rtx_1_5.dll`，插件按
`<自身目录>\vsmlrt-cuda\tensorrt_rtx_1_5.dll` 预加载，替换成别的代次会加载失败。

## 模型不在包内

与上游 mpv_PlayKit 的 vsNV 包一致，模型需要自己放到 `vs-plugins/` 对应目录：

- 超分：`vs-plugins/models/cugan/`（如 `pro-conservative-up2x.onnx`）
- 降噪/去块：`vs-plugins/models/dpir/`（`drunet_*.onnx`）
- 补帧：`vs-plugins/librife_windows_x86-64.dll` + 对应 `rife` 模型

没有模型时 K7sfunc 的 TRT-RTX 预设会降级并在 OSD 提示，不算故障。
