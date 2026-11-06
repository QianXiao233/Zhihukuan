"""决策大脑包。

模块划分：
- :mod:`brain.world_model` —— LSTM 世界模型与米/原始刻度换算
- :mod:`brain.planner`     —— MPC 候选规划与代价函数（动作空间为档位 0..N）
- :mod:`brain.gates`       —— 多闸门协调：档位 → 具体闸门组合 + 磨损均衡
- :mod:`brain.learner`     —— 经验回放与自适应在线学习
- :mod:`brain.gate`        —— 开闸确认与冷却状态机
- :mod:`brain.engine`      —— 把以上组合成完整决策内核
"""

from brain.engine import BrainConfig, DamBrain
from brain.gate import ConfirmationConfig, GateController, GateState
from brain.gates import CoordinationConfig, GateArray
from brain.learner import LearningConfig, OnlineLearner
from brain.planner import CostWeights, Decision, MpcPlanner, PlanningConfig, WaterLevels
from brain.world_model import WaterScale, WorldModel, WorldModelRunner

__all__ = [
    "BrainConfig",
    "ConfirmationConfig",
    "CoordinationConfig",
    "CostWeights",
    "DamBrain",
    "Decision",
    "GateArray",
    "GateController",
    "GateState",
    "LearningConfig",
    "MpcPlanner",
    "OnlineLearner",
    "PlanningConfig",
    "WaterLevels",
    "WaterScale",
    "WorldModel",
    "WorldModelRunner",
]
