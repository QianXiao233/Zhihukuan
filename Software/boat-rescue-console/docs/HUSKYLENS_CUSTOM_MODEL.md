# HUSKYLENS 2 自定义模型：溺水人员识别（训练 → 打包 → 部署）

本文是把「模拟溺水人员（人形假人）」训练成检测模型并部署到 **HUSKYLENS 2** 的完整手册。
所有约束都来自 DFRobot 官方文档（<https://wiki.dfrobot.com/sen0638/docs/22604>），照做即可。

---

## 0. 先记住四条硬约束

| 项 | 约束 |
| :--- | :--- |
| 设备 | HUSKYLENS 2（SEN0638，K230，6TOPS）；**固件 ≥ 1.1.6**（系统设置 → 设备信息查看） |
| 任务 | 只支持**目标检测 / 图像分类 / 实例分割**；我们要的是目标检测 |
| 架构 | **只支持 YOLOv8n / YOLO11n**（`-cls`/`-seg` 对应分类/分割）；YOLOv5、YOLOv8s、YOLO11s 都不行 |
| 输入尺寸 | 只能 **224 / 320 / 640**，训练时用哪个，导出 ONNX 就必须用哪个 |

数据集用 **YOLO 格式**（`images/train` + `labels/train` + `data.yaml`，`val` 建议有），每类至少 10 张；
实际效果好坏几乎完全取决于数据是否"像现场"。

---

## 1. 采数据（最影响效果的一步）

模型最终跑在**船头的二哈相机**上，所以训练图要尽量用**同一个视角**拍：

- **首选：直接用二哈识图 2 拍照**。设备内置「照相机」应用，拍照默认存 TF 卡；
  拍完把 TF 卡插读卡器拷到电脑。这样训练图与推理图来自同一个镜头、同一套色彩。
- 次选：手机/相机，但保持与船上安装一致的高度和俯仰角（船头向前、略向下看水面）。
- **数量**：同一个假人 **150–300 张**（标注框只要一类）。
- **多样性**（比数量更重要）：
  - 距离：0.3 m / 0.6 m / 1 m / 2 m / 3 m；
  - 方位：正前方、左/右 30°、偏转姿态（假人朝向不同）；
  - 光照：顺光、逆光、阴天/室内灯、水面强反光；
  - 水面：平静、波纹、有水花/尾迹；
  - 遮挡：假人只露出一部分、被水波挡住半边、靠近池壁；
  - 负样本：**空水面、橙色浮球、救生圈、岸上杂物**各拍 20~30 张（不标注，作为背景负样本，能显著压误检）。
- 采集完按下面结构放好（图片与同名 txt 标注）：

```text
raw/
├── images/            # 全部原图（jpg/png）
└── labels/            # 与图片同名的 YOLO txt（标注后才有）
```

> **录了视频可以先抽帧**：`extract_frames.py --input videos\ --out raw\images --every 5 --max 300`
> （自动跳过模糊帧和几乎重复的帧，比逐张拍省事）。

## 2. 标注

- 工具任选：**X-AnyLabeling**（支持 AI 辅助，推荐）、LabelImg（最简单）、Roboflow（在线）。
- 类别只建一个，命名建议 `drowning_person`（类别 id 必须从 0 开始且连续）。
- 每张图一个 `.txt`，每行 `类别id cx cy w h`（归一化到 0~1）。
- 标注原则：**框住假人露出水面的可见部分**（不要框到水下/倒影），贴边目标也要框全。
- **先预标注再人工修**（省时间）：`prelabel.py --images raw\images --onnx <任意可用 onnx> --out raw\labels --conf 0.3`
  → 生成 YOLO txt + 画框预览，人工只做补漏/删误；空水面负样本默认不写 txt，确认后加 `--write-empty`。

## 3. 划分数据集

> **先自检环境**：`python selftest.py`（依赖、视觉回归、已有产物、打包环境、固件产物一次过一遍）。
>
> **想少打字直接一条命令**：
> `python build_model.py --raw raw --app-name 溺水人员检测 --application Drowning_Person`
> 自自动完成 划分 → 训练 → 自检 → 出安装包（下面的 3~6 节是它的手动拆解）。

```powershell
cd E:\Users\CKJ\Desktop\Zhihukuan\Software\boat-rescue-console\vision\training
D:\miniconda3\python.exe split_dataset.py --src raw --out dataset --val-ratio 0.2 --class-name drowning_person --allow-empty-labels
```

> - `--src`（等价旧写法 `--raw`）：原始图片 + 同名 txt 的目录；
> - `--allow-empty-labels`：把**空 txt** 当负样本，**带空标注一起进数据集**（YOLO 会把空标注文件当背景负样本训练）。
>   只有图、没有 txt 的文件仍默认报错（可 `--allow-missing-labels` 跳过），所以负样本请建 0 字节 txt，
>   或用 `prelabel.py --write-empty` 生成；负样本对压误检很重要（建议占 10~15%）。
> - 真实数据建议按**拍摄批次/光照/水域**划分（`--split hash` 或手工分目录），
>   别用纯随机划分，否则同一场景的近似帧自泄漏到 val，指标虚高。

产物：

```text
dataset/
├── data.yaml            # names: {0: drowning_person}
├── images/train|val
└── labels/train|val
```

脚本自校验：每张图都有同名标注、类别 id 连续、坐标合法；缺标注自直接报错，不自悄悄漏训。

## 4. 训练并导出 ONNX

```powershell
# 预训练权重从 HuggingFace 下（本机 github 不通，ultralytics 自动下载自卡住）
#   https://huggingface.co/Ultralytics/YOLO11/resolve/main/yolo11n.pt
D:\miniconda3\python.exe train.py --data dataset\data.yaml --model weights\yolo11n.pt --imgsz 640 --epochs 100
```

- `train.py` 训练结束自自动 `export(format="onnx", imgsz=640)`，产物在
  `runs/train/<name>/weights/`（`best.pt` / `best.onnx`，`<name>` 由 `--name` 指定，
  默认是 `train`；注意不是 ultralytics 默认的 `runs/detect/train/`，本项目显式把 project 设成了 `runs/train`）。
- **imgsz 必须与打包时填的输入尺寸一致**（推荐 640；显存/帧率紧张可用 320，但要重训）。
- 单类、150~300 张、RTX 5060：100 epoch 大约十几分钟到半小时。

## 5. 打包前自检（强烈建议）

```powershell
D:\miniconda3\python.exe check_onnx.py --onnx runs\train\<name>\weights\best.onnx --data dataset\data.yaml --imgsz 640 # 真实数据可放宽到 --min-recall 0.85 --min-precision 0.7
```

输出 precision/recall（IoU 0.5）并在 `runs/check/` 画框。**合成数据验证要求 ≥0.9；真实数据一般
≥0.85 再上设备**，否则先补数据（尤其是逆光、远距离、水花遮挡这几类最常漏）。

## 6. 生成二哈安装包

### 6.1 一键打包（推荐，已实跑验证）

官方工具的内核是纯 Python。本仓库封装了 `vision/training/package_huskylens.py`，
直接复用官方 `data_preparation.py` + `convertor.py`（nncase PTQ），一条命令出包：

```powershell
cd Software\boat-rescue-console\vision\training
D:\miniconda3\python.exe package_huskylens.py `
  --dataset dataset `
  --onnx runs\train\drowning\weights\best.onnx `
  --app-name 溺水人员检测 `
  --application Drowning_Person `
  --threshold 0.4
```

产物形如 `runs/package/<app>-YOLO11n-det-640.<4位校验>.zip`（YOLOv8n 同样支持，已实测
`TestV8-YOLOv8n-det-320` 能正常出包并通过校验），包内结构（与官方 Model Hub
安装包逐项一致，已对比验证）：

```
app.<application>          # 空文件，标记应用
conf.json                  # 应用名/类别/阈值/模型信息
<application>.kmodel       # nncase 量化后的 K230 模型
desc.json                  # 多语言显示名
icon.png                   # 图标
```

> 脚本自先校验 **ONNX 输出类别数 == data.yaml 类别数**（比如拿 80 类的 COCO 模型去配
> 1 类数据集自直接报错并退出），避免打出一个"框对不上名字"的应用；确认无误可加
> `--allow-class-mismatch` 跳过。

环境准备（一次性）：

```powershell
# 1) 官方源码（Gitee 镜像，github 本机不通）
git clone --depth 1 https://gitee.com/dfrobot/onnx2kmodel D:\tools\huskylens\src
# 2) nncase + 官方 KPU 插件（wheel 在源码目录里）；版本与官方打包器对齐：nncase 2.10.0
D:\miniconda3\python.exe -m pip install "nncase==2.10.0" "D:\tools\huskylens\src\nncase_kpu-2.10.0-py2.py3-none-win_amd64.whl" tomlkit pyyaml pillow onnx
```

> - **版本钉死 nncase 2.10.0**（与官方打包器 `requirements.txt` 的 `nncase>=2.10.0` + 自带
>   `nncase_kpu-2.10.0` wheel 一致）。已实测：2.11.0 与 2.10.0 对 K230 目标输出的 kmodel
>   **字节完全相同**（同 md5），所以 2.11 也不会打坏包；钉 2.10 是为了可复现。
> - 产物 kmodel 文件头为 `LDMK` + 版本 `0x07`（K230 kmodel v7），与官方工具一致。
> - nncase 2.x 的 hostfxr 声明 .NET 7.0.0；本机只有 8/10 时脚本会自动设
>   `DOTNET_ROLL_FORWARD=LatestMajor` 前滚，**不用装已 EOL 的 .NET 7**。
> - `--application` 用纯英文更稳妥（包内文件名）；设备上显示的仍是 `--app-name`
>   （中文）以及 `desc.json` 里的多语言名。
> - 打包是本地量化（UINT8，NoClip，10~20 张校准图），640 模型约 1~2 分钟。

### 6.2 图形界面（等价流程，手上只有 exe 时用）

工具在 `D:\tools\huskylens\generator\HUSKYLENS2_Package_Generator.exe`
（官方仓库 Gitee 镜像 v1.0，已启动验证）。

1. 双击打开（标题「HUSKYLENS 2 模型安装包生成器」），顶部三项：
   - **界面语言**：中文；
   - **输出目录**：选一个空目录，例如 `D:\tools\huskylens\output`；
   - **数据源**：保持 `YOLO`。
2. **Dataset Folder** → 选第 3 步的 `dataset`（含 `data.yaml`）；
3. **ONNX Model** → 选 `best.onnx`；
4. 核对自动识别的参数：**任务类型 = 目标检测**、**模型 = YOLO11n**、**输入尺寸 = 640**（必须与训练一致）；
5. **App Name** 填 `溺水人员检测`（设备上显示的名字；中文每行最多 6 字、最多两行）；
   可选 **Choose Icon** 换图标（60×60 透明 PNG）、设默认置信度（建议 0.40）；
6. 点 **Start**，等完成。产物文件名形如
   `溺水人员检测-YOLO11n-det-640.<校验>.zip`
   ⚠️ **不要改 zip 的文件名，也不要解压/改动里面的内容**。

## 7. 安装到二哈

1. USB 线连电脑，资源管理器出现名为 **HUSKYLENS 2** 的 U 盘；
2. 把 zip 拷到：`HUSKYLENS 2\storage\installation_package\`
   （也可以用脚本自动找盘并拷贝：`python tools\hardware_check.py --install runs\package\<xxx>.zip`）；
3. 设备屏幕：**模型安装 → 本地安装**，选中刚拷的包；
4. 安装成功后，功能列表里出现「溺水人员检测」；
5. 点进去对着假人试一下，确认能框住、置信度合适（不行就调到设备里的默认阈值）。

## 8. 让无人艇用上这个模型（固件只改一个宏）

**先确认哪块板子是哪块**（主控和桥接板 USB VID/PID 相同，别烧错）：

```powershell
cd Software\boat-rescue-console\tools
D:\miniconda3\python.exe hardware_check.py --read --reset
```

脚本按启动日志的 TAG 区分：`BOAT_*` = 船载主控、`BRIDGE_*` = 桥接板，并打印各自的烧录命令；
它还自顺带检查二哈 U 盘和当前固件打印的 `HUSKYLENS 算法 ID`。

自定义模型的**算法 ID 不是内置的 1~19**。官方协议文档（`HuskyLens2_Protocol_CN.md`，
在 Arduino 库目录 `Documents\Arduino\libraries\DFRobot_HuskylensV2\` 下）明确：
**算法 ID 128~255 专门留给用户安装的模型**，而且 `SET_ALGORITHM` 自回
`RETURN_ARGS(retValue=0 成功)` —— 所以既可以手填 ID，也可以让固件自己探测。

```c
// Hardware/Firmware/boat/controller-idf/main/shared/boat_controller_config.h
#define HUSKY_ALGORITHM_ID  131   // 方式一：填设备上显示的算法 ID（推荐，开机快）
// #define HUSKY_ALGORITHM_ID  0  // 方式二：0 = 开机自动扫描 128~255，找到就用（多花几秒）
```

**方式二（自动探测）**：填 0 后固件自逐个调 `SET_ALGORITHM` 并看返回值，找到第一个可用的
用户模型 ID 就切过去；找不到回退内置物体追踪（3）。扫描有 20 s 预算，不自把开机卡死，
日志自打印：

```
发现用户模型算法 ID=131（用时 375 ms）
自动探测成功，算法 ID=131（建议把它写进 HUSKY_ALGORITHM_ID 以跳过开机扫描）
```

探测到之后把该值写回宏、重烧一次，之后开机就不用再扫。

然后重新编译烧录船载主控（端口用 `hardware_check.py` 识别出来的那个，别用桥接板的）：

```powershell
cd Hardware\Firmware\boat\controller-idf
. .\idf-env.ps1
idf.py -p COM10 flash monitor
```

启动日志自打印 `HUSKYLENS 2 初始化成功（算法 ID=131，配置=131）`；之后船端的
`target_seen / x / y / width` 就来自这个自定义模型，**末端跟踪、40 cm/20 cm 停车逻辑完全不用改**
（协议 `RETURN_BLOCKS` 前 10 字节固定，类名/内容追加在后面，驱动只解析前 10 字节）。

## 9. 上位机也接这个模型（可选，注意视角）

上位机已经接好，**改两个配置就行**（`Software/boat-rescue-console/vision/config.py`）：

```python
YOLO_MODEL = ""              # 留空=自动找 models/ 下的固定名字；可填 "drowning_person.onnx"
                             #（相对 models/）或绝对路径（临时验证训练产物最方便）
YOLO_INPUT_SIZE = 640        # 与训练/导出一致：320 的模型就改 320（填错会被自动纠正，见下）
```

> 检测器启动时会**自动读取 ONNX 的输入尺寸**并与 `YOLO_INPUT_SIZE` 对齐：不一致时打印一行
> 提示并自动改用模型实际尺寸（需要装 `onnx`；没装则按配置值走）。这样"尺寸填错导致框整体
> 缩放错、还不报错"的坑就不会发生——已用 320 模型（配置仍写 640）实测自动纠正到 320。

也可以在代码里直接指定：`Detector(model_path=r"...\best.onnx", yolo_input_size=640)`。

**已验证**：把二哈训练产出的单类 ONNX（`1x5x8400`，class 0）交给 `detector.py` 的
ONNX 后端解码（letterbox + NMS），在合成验证集 20 张上 **P=1.000 / R=1.000** —— 单类 `nc=1`
输出、class 0 约定和检测器是兼容的。

**但视角限制依然存在**（重要）：
- 模型按**船头二哈视角**（低角度、贴近水面）训练；`locator.py` 的相机是顶端俯拍 UVC，
  两者差异很大 —— 拿它跑俯拍画面效果会很差，**不要期望它替代原有检测器**；
- 想给 PC 的俯拍相机用，需要**另采俯拍视角数据**重训一个模型（同一套工具链，
  只换 `--raw` 和 `--app-name`），然后同样通过 `YOLO_MODEL` 指过去；
- 想单独验证模型本身：用 `prelabel.py` 喂船头角度的图，或看 `runs/prelabel/` 的画框预览。

## 10. 打包前 / 拷卡前自检

```powershell
# 数据集体检（训练前）：配对、标注合法性、框分布、train/val 近似重复（泄漏）
D:\miniconda3\python.exe dataset_report.py --data dataset --out runs\dataset_report.json

# 量化自检（打包前，不需要硬件）：K230 目标逐层 SQNR/余弦，重点看最终输出层
D:\miniconda3\python.exe quantize_check.py --k230-dump --onnx runs\train\drowning\weights\best.onnx --dataset dataset

# 安装包自检（拷到设备前）：文件名、5 个内部文件、conf/desc 结构、kmodel 文件头、zip CRC
D:\miniconda3\python.exe verify_package.py runs\package\<应用名>-YOLO11n-det-640.<xxxx>.zip
```

- `dataset_report.py`：重点看「跨 train/val 近似重复」是否为 0、每图框数中位数、极小框占比；
  有泄漏就按拍摄批次重新划分，否则 val 指标自虚高。
- `verify_package.py`：只认官方结构；我们生成的包和官方 Model Hub 的 `-DF` 包都能通过校验。

## 11. 常见问题

| 现象 | 原因 / 处理 |
| :--- | :--- |
| 设备上看不到「模型安装」 | 固件 < 1.1.6，先升级固件 |
| 包拷贝后"本地安装"里没有 | zip 被改名/解压过；必须原样放 `storage/installation_package` |
| 生成器报模型不支持 | 只支持 YOLOv8n/YOLO11n；检查 `task=detect`、输入尺寸 224/320/640 |
| 设备上框得很差 | 训练图与现场视角/光照差异太大；补拍逆光、远距离、水花遮挡样本后重训 |
| 误检岸上橙色物体 | 加入对应负样本（空水面/浮球/杂物）重训；或把设备默认置信度调到 0.5+ |
| 船端识别不到 | `HUSKY_ALGORITHM_ID` 没改成设备实际 ID；或算法在设备侧未切到该功能。可先把它设成 `0` 重新烧录，让固件自动扫描 128~255 并把找到的 ID 打进日志 |
| PC 上跑这份模型效果差 | 视角不匹配（俯拍 vs 船头低角度），需要单独采俯拍数据重训 |

## 12. 文件清单

| 位置 | 说明 |
| :--- | :--- |
| `vision/training/` | 采集/抽帧/预标注/划分/训练/自检/打包/安装包校验 全套脚本 |
| `D:\tools\huskylens\generator\` | 官方 Package Generator（Gitee 镜像 v1.0） |
| `D:\tools\huskylens\src\` | 官方 onnx2kmodel 源码（`package_huskylens.py` 复用其内核） |
| `Hardware/Firmware/boat/controller-idf/` | 船载固件（`HUSKY_ALGORITHM_ID` 在此配置） |
| `Software/boat-rescue-console/vision/models/` | PC 侧 ONNX 兜底（可选） |
