"""
视觉定位配置

HSV 阈值**必须按现场实际光照调整** —— 相机不同、灯光不同、水面反光不同，
同一组阈值换环境就会失效。推荐用取色工具现场测：

    python pick_hsv.py            # 鼠标点选目标，实时打印 HSV 值

然后把结果填到 TARGET_HSV_RANGES 里。OpenCV 的 H 范围是 0~179，S/V 是 0~255。
"""

# ---------------- 相机 ----------------
CAMERA_INDEX = 0
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080
# 俯拍定位不需要高帧率，但相机默认可能给 MJPG；设成 MJPG 才能拿到高分辨率
CAMERA_FOURCC = "MJPG"

# ---------------- ArUco ----------------
ARUCO_ID = 0
ARUCO_DICT_NAME = "DICT_4X4_50"    # 与打印的码一致
MARKER_SIZE_M = 0.09               # 打印码的实际黑边边长（仅文档/打印用；坐标不依赖它）

# ---------------- 目标颜色 ----------------
# 格式: (H_min, S_min, V_min), (H_max, S_max, V_max)
# H 跨越 0/179 时需要写两段（红色就是典型例子）。
# 下面给的是"橙色"的经验值，仅作起点，务必现场校准。
TARGET_HSV_RANGES = [
    ((5, 120, 120), (22, 255, 255)),      # 橙色主段
]

# 目标最小轮廓面积（像素²）。设太小会把噪点当目标，太大则远距离目标检不到。
MIN_TARGET_AREA_PX = 300

# 形态学去噪核大小（对水面高光/波纹产生的碎斑很有用）
MORPH_KERNEL = 5

# ---------------- 上报 ----------------
SERVER_URL = "http://127.0.0.1:4174"
REPORT_HZ = 20                     # 上报频率；与船端 20Hz 主循环匹配

# 定位结果合理性检查：船/目标坐标超出水池边界这么多（米）就判为误检、不上报。
# 作用相当于最后一道地理围栏：宁可停船，也不要把离谱坐标发给船。
POOL_REPORT_MARGIN_M = 0.10

# 目标丢失多少帧后判定为"丢失"（避免单帧抖动导致坐标跳变）
TARGET_LOST_FRAMES = 10

# ---------------- 识别与自主规划（v1.7） ----------------
# 识别：detector.py 的融合检测（HSV + 形状打分 + 时序跟踪，可选 ONNX 人形模型）。
# False 时退回 target.py 的纯 HSV 实现（老路径，用于对比/回滚）。
USE_FUSED_DETECTOR = True

# 规划：planner.py 的 A* + LOS 平滑 + 纯追踪。
# True 时下发给船的是"沿路径前方的虚拟目标点"（保证 >0.4m，避免船端提前切二哈末端）；
# False 时沿用旧行为，直接把真实目标坐标发下去。
USE_PLANNER = True
PLANNER_LOOKAHEAD_M = 0.55      # 纯追踪前视距离，必须明显大于船端 0.4m 的末端切换半径
PLANNER_RESOLUTION_M = 0.05     # 规划栅格分辨率（1.2m 池子 -> 24x24）
PLANNER_BOAT_RADIUS_M = 0.09    # 船体外接半径，用于边界膨胀
PLANNER_CLEARANCE_M = 0.05      # 额外安全余量

# 无目标时是否让船按弓字形覆盖搜索。
# 默认关闭：开启后 locator.py 一运行船就会自己动起来（台架调试很危险）。
# 演示/搜救时用命令行 --search 打开。
SEARCH_WHEN_NO_TARGET = False

# 融合检测的最低置信度（0~1），低于该值视为未检测到
DETECT_MIN_CONFIDENCE = 0.35

# ONNX 人形/目标模型（cv2.dnn，不需要 torch/onnxruntime）。
# 模型放在 vision/models/yolov8n.onnx，缺失时自动禁用、只提示一次。
# 每 YOLO_EVERY_N 帧推理一次（1080P 纯传统 3ms/帧，开 ONNX 后约 15ms/帧）。
YOLO_ENABLED = True
YOLO_EVERY_N = 4
YOLO_CONF = 0.35

# 指定 ONNX 模型（可选）：
#   留空   = 按 models/ 里的固定名字自动查找，再退而求其次找任意 *.onnx
#   文件名 = 相对 vision/models/ 解析（如 "drowning_person.onnx"）
#   绝对路径 = 直接用（方便临时验证训练产物，不必拷进 models/）
# 注意：**模型是哪个视角训练的就只能用在哪个视角**。船头二哈视角训的模型
# 不要拿来跑顶部俯拍相机；单类自定义模型 class 必须是 0（detector 只取 class 0）。
YOLO_MODEL = r"E:\Users\CKJ\Desktop\Zhihukuan\Software\boat-rescue-console\vision\training\runs\train\topview_v1\weights\best.onnx"
# 模型输入尺寸，必须与训练/导出时一致（224/320/640）。自定义模型是 320 就改 320。
YOLO_INPUT_SIZE = 640
