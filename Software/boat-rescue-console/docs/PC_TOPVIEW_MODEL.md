# 顶视摄像头落水识别模型（电脑端）操作手册

> 适用场景：**只在电脑上跑**，用顶部俯拍摄像头（UVC）识别池中的"模拟溺水人员"，
> 不需要 HUSKYLENS 2、不需要打包 kmodel、不需要烧固件。
>
> 与二哈那套的区别只有两点：**训练数据换成顶视视角**、**产物只留 ONNX**。
> 训练/标注/体检工具完全相同。二哈流程见 [`HUSKYLENS_CUSTOM_MODEL.md`](./HUSKYLENS_CUSTOM_MODEL.md)。

---

## 0. 一句话流程

```
顶视相机采图 → 预标注打底 → X-AnyLabeling 修正 → build_model.py --onnx-only
→ config.py 指向 ONNX → locator.py --show 验证
```

---

## 1. 关键前提：视角必须和训练一致

模型只认识"它训练时看到的画面"。所以：

- **采集机位 = 最终安装机位**：同一摄像头、同一高度、同一俯仰角、同一焦距；
- 采集后**机位就别再动**；动了就得重拍；
- 船头低角度训出来的模型**不能**用于顶视，反之亦然（`detector.py` 不会报错，只会效果很差）。

> 如果最终会换镜头（比如先用手机会后用 UVC 相机），请**直接用最终那个相机采数据**。

---

## 2. 采集（150~300 张）

### 2.1 相机与画面

| 项 | 建议 |
|---|---|
| 分辨率 | 1080P（1920×1080）。更高分辨率不会更准，只是更慢 |
| 机位 | 正上方或略偏，覆盖整个 1.2m×1.2m 水池 + 一点池边 |
| 目标大小 | 假人在画面里的短边建议 ≥ 40 px（640 输入下约 6%） |
| 光照 | 至少覆盖顺光/逆光/阴天或室内灯/水面强反光四种 |

### 2.2 要拍哪些

- **位置**：池中心、四角、贴池壁各来几张（覆盖全池）；
- **距离/尺度**：能拍到的最远、最近都要；
- **姿态**：仰面、俯卧、侧身、单臂上举、蜷缩、只露头肩；
- **水面**：平静、波纹、有水花/尾迹；
- **遮挡**：只露一部分、被波纹盖住半边、靠近池壁；
- **负样本（20~30 张，重要）**：空水面、池壁、水面反光、浮球/救生圈、岸上杂物/人影。

### 2.3 放哪儿

```text
Software/boat-rescue-console/vision/training/raw_top/
├── images/     # 全部原图（jpg/png）
└── labels/     # 与图片同名的 YOLO txt（标注后才有）
```

> 拍的是视频也可以用 `extract_frames.py` 抽帧：
> `python extract_frames.py --input videos_top\ --out raw_top\images --every 5 --max 300`

---

## 3. 标注（X-AnyLabeling，本机已装 4.2.0）

### 3.1 先跑一遍预标注打底

```powershell
cd Software\boat-rescue-console\vision\training
D:\miniconda3\python.exe prelabel.py `
  --images raw_top\images `
  --onnx ..\models\yolov8n.onnx `
  --out raw_top\labels `
  --conf 0.30
```

- 用的是 COCO person 模型（`vision/models/yolov8n.onnx`）；假人如果长得像人，能给出粗框；
- **框不出来就纯手标**，不影响后面的流程；
- 预览图在 `runs/prelabel/`，可以先整体翻一遍看哪些图值得留。

### 3.2 用 X-AnyLabeling 修正

```powershell
D:\miniconda3\Scripts\xanylabeling.exe --filename raw_top\images
```

操作要点：

1. 它会自动加载同目录/同名 `.txt`（YOLO 格式）作为初稿；
2. 类别**只建一个**，名字用 `drowning_person`（或 `person_in_water`），**类别 id 必须是 0**；
3. 快捷键：`W` 画框、`Ctrl+S` 保存、`D`/`A` 下一张/上一张、`Ctrl+滚轮` 缩放；
4. 保存格式选 **YOLO**（默认就是，导出时确认一下）。

### 3.3 标注规则（直接决定模型质量）

- **框住目标露出水面的可见部分**：不要框水下模糊的影子、不要框倒影；
- 贴边目标也要框全（框超出画面没关系，YOLO 会裁剪）；
- 看不清的帧**不标**，但保留图片（它自然成为负样本的候选）；
- 不要用"框住整个水池"这种大框凑数，模型会学错尺度；
- 负样本：保留图，建**同名 0 字节 txt**（或者直接不建 txt，后面用 `--allow-missing-labels`）。

> 标完可以抽查：`python prelabel.py --images raw_top\images --onnx <刚训的 onnx> --out runs\check_labels --preview runs\check_labels_preview`
> 看模型预测和你标的框是否大致重合。

---

## 4. 训练（一条命令，只出 ONNX）

```powershell
cd Software\boat-rescue-console\vision\training
D:\miniconda3\python.exe build_model.py `
  --raw raw_top `
  --dataset runs\dataset_top `
  --name topview `
  --imgsz 640 `
  --class-name drowning_person `
  --epochs 100 `
  --onnx-only `
  --app-name 顶视落水检测
```

说明：

- `--onnx-only` 会跳过量化自检和二哈打包，**训练 + 精度自检完就停**，直接告诉你 ONNX 路径和电脑端接法；
- `--imgsz 640`：顶视里目标偏小，**不要用 320**；
- 自检默认门槛 `recall≥0.85 / precision≥0.70`（真实数据别指望 0.9）；**漏检代价更大，宁可压低阈值**；
- 样本 <300 张时可用 `--epochs 150 --patience 30`；
- 想同时留二哈安装包，去掉 `--onnx-only` 即可（那会多跑量化自检 + 打包）。

产物：

```
runs/train/topview/weights/best.pt      # PyTorch 权重
runs/train/topview/weights/best.onnx    # ← 电脑端用的就是这个
runs/train/topview/train_summary.json   # 参数/指标/ONNX I/O 形状
```

---

## 5. 接进上位机

### 5.1 改配置（推荐）

`Software/boat-rescue-console/vision/config.py`：

```python
YOLO_ENABLED = True
YOLO_EVERY_N = 4          # 每 4 帧推理一次；640 CPU 单次约 30~40ms，摊到每帧 ~15ms
YOLO_CONF = 0.40          # 顶视误检多的话提到 0.5
YOLO_MODEL = r"E:\...\runs\train\topview\weights\best.onnx"   # 绝对路径或相对 models/
YOLO_INPUT_SIZE = 640     # 填错会被自动纠正（读 ONNX 输入尺寸）
```

### 5.2 验证

```powershell
cd Software\boat-rescue-console\vision
D:\miniconda3\python.exe locator.py --show
```

- 启动日志出现 `YOLO 后端已启用: best.onnx（... 输入 640，只取 class 0 person）`；
- 画面里假人出现时应有框（`--show` 会画出来），终端/网页能看到目标坐标；
- 继续跑既有流程即可（ArUco 定船位、目标框经 homography 转池内坐标）。

### 5.3 与原有检测器的关系

- 融合检测：**高置信 ONNX 框优先**，其余走传统 HSV；两者都经过水池 ROI 几何围栏（池外的框丢掉）；
- 只想看 ONNX 效果可以临时把 `YOLO_CONF` 压低、或直接用 `prelabel.py` 出预览看框，不动主流程；
- 顶视专用模型**不要**再丢给二哈打包（视角不对），二哈那份用船头视角数据单独训。

---

## 6. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 训练 loss 不降 / mAP 一直 0 | 类别 id 不是 0、或标注框全是同一个大框；用 `dataset_report.py --data runs\dataset_top` 查 |
| 上线后完全框不住假人 | 采集机位和部署机位不一致（最常见）；重拍 |
| 池壁/浮球被当目标 | 负样本不够（建议 10~15%）；或 `YOLO_CONF` 提到 0.5 |
| 假人在远处漏检 | 目标太小：换 640、机位拉近、或补拍远距离样本 |
| 视频卡顿 | `YOLO_EVERY_N` 调大（4→6/8）、或 `roi_max_side` 调小 |
| 报错 `找不到同名标注文件` | 负样本请建同名 0 字节 txt（+ `--allow-empty-labels`），或加 `--allow-missing-labels` |
| 验证集指标虚高 | 同场景近似帧泄漏：用 `--split hash`，并用 `dataset_report.py` 看「跨 train/val 近似重复」 |

---

## 7. 数据/模型自检清单

```powershell
# 训练前：配对、标注合法性、框分布、泄漏
D:\miniconda3\python.exe dataset_report.py --data runs\dataset_top --out runs\dataset_top_report.json

# 训练后：ONNX 精度（P/R/mAP50 + 画框）
D:\miniconda3\python.exe check_onnx.py --onnx runs\train\topview\weights\best.onnx --data runs\dataset_top\data.yaml --imgsz 640
```

通过标准（经验）：无跨集泄漏、每图框数中位 ≥1、极小框占比 <1%、负样本 10~15%、
真实数据 recall ≥0.85。

---

## 8. 与二哈流程的对照

| 步骤 | 本手册（电脑 / 顶视） | 二哈流程 |
|---|---|---|
| 采集机位 | 顶部俯拍 | 船头低角度 |
| 输入尺寸 | 640 | 640（也可 320） |
| 训练 | `build_model.py --onnx-only` | `build_model.py` |
| 量化自检 | 不需要 | `quantize_check.py --k230-dump` |
| 打包 | 不需要 | `package_huskylens.py` → zip |
| 部署 | `config.YOLO_MODEL` 指向 ONNX | 装 zip + 改 `HUSKY_ALGORITHM_ID` |
| 验证 | `locator.py --show` | 船端日志 + 水面实测 |

---

*文档版本：v1.0（与 Project.md v1.9 配套）*
