# vision/models —— 可选的人形检测模型放这里

`detector.py` 的 ONNX 后端是**可选增强**：这个目录里有模型就用，没有就静默退回纯 HSV
传统检测（只在进程启动时打印一行提示，不影响主流程）。**不装 torch 也能用**——推理走
`cv2.dnn`，只需要 `opencv-python`。

```
Software/boat-rescue-console/vision/
├── detector.py
├── models/                     <-- 本目录
│   ├── README.md               <-- 本文件（入库）
│   └── yolov8n.onnx            <-- 模型权重（不入库，见下）
```

## 1. 放哪个文件

按顺序查找，命中第一个就用（都在本目录下）：

| 优先级 | 文件名 | 说明 |
|---|---|---|
| 1 | `yolov8n.onnx` | 推荐：12.9 MB，CPU 640x640 前向约 30~40 ms |
| 2 | `yolo11n.onnx` | 同量级，新版 YOLO11 |
| 3 | `yolov8s.onnx` | 更准但约 45 MB，单帧前向 ~90 ms，1080P 下建议只做抽帧 |
| 4 | `yolo11s.onnx` | 同上 |
| 5 | `person.onnx` | 任意只含/含 person 类的 YOLOv8 导出 |

都没有时，目录里任意 `*.onnx` 会被当作候选。也可以用代码显式指定：

```python
Detector(model_path=r"D:\wherever\my_person.onnx")   # 相对路径按本目录解析
Detector(yolo_enabled=False)                          # 或直接关掉 ONNX
```

## 2. 怎么获取

### 方式 A：直接下官方导出好的 ONNX（最省事，本机已验证可用）

```powershell
cd Software\boat-rescue-console\vision\models
curl.exe -L -o yolov8n.onnx `
  "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.onnx"
```

本仓库开发时下载并验证过的就是这个文件：

| 项 | 值 |
|---|---|
| 大小 | 12,851,049 字节 |
| SHA-256 | `b2bc52f40e8e1c532427d5bde3575a5d5b571b739fab2c6df443733ed1589cbd` |
| producer | `pytorch 2.11.0`，IR 9，opset 20 |
| 输入 | `images`：`[1, 3, 640, 640]`（固定尺寸） |
| 输出 | `output0`：`[1, 84, 8400]` |
| 本机实测前向 | ~30~40 ms（CPU，1080P 帧内含预处理共 ~37 ms） |

校验下载是否完整：

```powershell
(Get-FileHash yolov8n.onnx -Algorithm SHA256).Hash.ToLower()
```

### 方式 B：自己导出（想换模型 / 想改成只含 person 类时）

导出需要一次性的 torch/ultralytics，**部署机不需要**：

```powershell
pip install ultralytics onnx onnxslim
yolo export model=yolov8n.pt format=onnx imgsz=640 opset=12 simplify=True
# 产物通常是 yolov8n.onnx，复制到本目录即可
```

> 注意：`imgsz=640`、`format=onnx`、导出后输出应是 `1x(4+类别数)xN` 的原始张量，
> **不要**再套 YOLOv5 那种 `[N, 85]` 的旧格式，也不要 include NMS（本项目自己做 NMS）。

### 方式 C：Hugging Face 镜像（GitHub 访问不了时）

```powershell
curl.exe -L -o yolov8n.onnx `
  "https://huggingface.co/onnx-community/yolov8n/resolve/main/onnx/model.onnx"
```

不同镜像的导出参数可能不同（输入尺寸 / 是否含 NMS / 类别数），放进去后按第 4 节自检一遍。

## 3. 为什么模型默认不进版本库

仓库根目录 `.gitignore` 里有 `*.onnx` 与 `models/`（"大体积权重不入库"），所以每台机器
需要自己下一份。这是有意的：12.9 MB 的模型跟着 git 走会让仓库越来越重，而且模型与代码的
版本没有任何绑定关系。

模型缺失时的行为（`detector.py`）：

* 启动时打印一次
  `[detector] 未找到 ONNX person 模型（目录 …\vision\models）；YOLO 后端已禁用，仅用传统检测。`
* 之后每帧只用传统检测，**不会**反复重试、不会报错、不会拖慢主循环。
* `d.info()["yolo_enabled"]` 为 `False`，`d.info()["notes"]` 里有完整提示文本。

## 4. 放进去之后怎么确认生效

不用相机，直接跑回归测试（最后两段就是 ONNX 相关）：

```powershell
cd Software\boat-rescue-console\vision
D:\miniconda3\python.exe test_detector.py
```

看到这两行就说明加载 + 推理 + 融合都通了：

```
[detector] YOLO 后端已启用: yolov8n.onnx（每 3 帧推理一次，输入 640，只取 class 0 person）
[OK] 13 真实 ONNX：yolov8n.onnx 已加载，640x640 单次前向 33.7 ms（每 3 帧一次）；本帧 source=classical
```

或者手动一行：

```powershell
D:\miniconda3\python.exe -c "import detector; d=detector.Detector(); print(d.info()['yolo_enabled'], d.info()['yolo_model'])"
```

## 5. 后端怎么工作的（和传统检测的配合）

1. 每 `yolo_every`（默认 3）帧做一次 640x640 推理：等比缩放 + 灰边填充（letterbox），
   BGR→RGB，`/255`，`cv2.dnn.blobFromImage(..., swapRB=True)`。
2. 解码 `1x84xN`：前 4 行是 `cx, cy, w, h`（640 输入像素），后 80 行是 COCO 类别分数
   （已过 sigmoid）。取 `argmax` 类别，只保留 **class 0 = person**。
3. `cv2.dnn.NMSBoxes` 去重（`yolo_conf` 过滤 + `yolo_iou` 抑制）。
4. 框的**底边中点**（水面接触点，而不是框中心）经 letterbox 反变换回原图，再用 H 映射到
   水池米坐标；不在水池内的框直接丢弃（和传统路径同一道几何围栏）。
5. 融合：人形置信度 `>= yolo_priority_conf`（默认 0.45）时优先用人形；否则用传统检测；
   传统检测什么都没找到时，低置信人形也接受（比 `None` 更有用——船会继续有目标点）。

可调参数（构造函数）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `yolo_enabled` | `True` | 总开关；`False` 完全不加载模型 |
| `yolo_every` | `3` | 每几帧推理一次（其余帧复用上次结果，摊平耗时） |
| `yolo_conf` | `0.35` | 检出底噪，低于它的框直接丢 |
| `yolo_iou` | `0.45` | NMS 的 IoU 阈值 |
| `yolo_priority_conf` | `0.45` | 高于它才"压过"传统检测 |
| `yolo_classes` | `(0,)` | 只保留这些类别（COCO 里 0=person） |
| `yolo_input_size` | `640` | 网络输入边长；换成 320 可再快 ~3 倍、但小目标更差 |
| `yolo_max_frame_side` | `1280` | 推理前把大图先缩到这个长边（1080P/4K 省时间） |

> 如果只想检测"落水的人"而不想被岸上的人误导：本项目已经用 **水池 ROI 几何围栏** 解决
> ——底边中点不在水池范围内的框会被丢掉，所以岸上的人不会成为目标点。
>
> 想进一步降误报，可以导出只含 `person` 一个类的模型（`nc=1`，输出变成 `1x5xN`，
> 解码器同样支持），并把 `yolo_conf` 提到 0.5 左右。

## 5.1 用二哈训练出的自定义模型

`vision/training/` 训出来的单类 ONNX（class 0 = `drowning_person`）也可以给上位机用，
两种接法任选：

```python
# 方式一（推荐）：改 config.py，locator.py 会自动带上
YOLO_MODEL = "drowning_person.onnx"   # 相对本目录；也可写绝对路径临时验证
YOLO_INPUT_SIZE = 640                 # 与训练/导出一致；填错会被自动纠正（见下）

# 方式二：代码里显式指定
Detector(model_path=r"D:\runs\train\drowning\weights\best.onnx", yolo_input_size=640)
```

> 装没装 `onnx` 都能跑：装了会**自动读取模型输入尺寸**并与 `YOLO_INPUT_SIZE` 对齐，
> 不一致时打印一行提示并自动改用模型的实际尺寸（320/640/224），避免"尺寸填错、框整体缩放错"
> 这种不报错的坑；没装 `onnx` 则按配置值走，建议手动核对。

**已验证**：单类 `nc=1` 输出（`1x5x8400`）在 `detector.py` 解码 + NMS 下，合成验证集
20 张 **P=1.000 / R=1.000**，class 0 约定与检测器完全兼容。

⚠️ **视角限制**：自定义模型按船头二哈视角（低角度、贴近水面）训练，不能直接替代
顶端俯拍相机上的检测器。要在 PC 的俯拍画面上用，需要另采俯拍数据重训一个模型。

## 6. 许可

Ultralytics 官方发布的 YOLOv8/YOLO11 权重与代码采用 **AGPL-3.0**（商用需另购企业许可）。
本项目是竞赛/教学用途的校内项目，直接使用官方权重没有问题；若要商用或闭源分发，请换成
许可兼容的模型（并在 `yolo_classes` 里指对 person 类），或购买 Ultralytics 企业许可。
