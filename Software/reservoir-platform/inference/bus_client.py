"""后端「服务接入」总线客户端。

为什么待确认请求要走总线，而不是让前端直连本服务？
-------------------------------------------------
两类数据的性质不同：

* **实时状态**（水位、闸门、最近决策）是高频快照。走消息队列只会引入延迟与
  堆积，直连本服务的 HTTP 接口才是对的。
* **待确认开闸请求**是「需要人处理的任务」。它必须落库、必须有至少一次的
  投递保证、必须能审计谁在什么时候批了/拒了。这正是总线的职责。

所以本模块只做一件事：把 `pending` 事件 publish 到后端总线（`brain.pending`），
由前端通过既有 SSE 频道（`ui.#`）接收并弹窗。

协议（对齐后端 `BusController`）
--------------------------------
- 端点：`POST {base}/api/bus/publish`
- 认证：`Authorization: Bearer <clientId>.<secret>`
- 请求体：`{"topic": "...", "type": "...", "payload": {...}}`

客户端凭据在平台「服务接入」页创建，配置到环境变量：
`BUS_BASE_URL`、`BUS_CLIENT_ID`、`BUS_CLIENT_SECRET`。

失败绝不阻塞决策：总线上报失败只记日志。开闸动作本身不依赖它。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import urllib.error
import urllib.request
import json

log = logging.getLogger(__name__)


@dataclass
class BusConfig:
    """总线连接配置。`enabled` 由是否配置了凭据决定。"""

    base_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    pending_topic: str = "brain.pending"
    approval_topic: str = "brain.approval"
    timeout: float = 5.0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "BusConfig":
        import os

        def env(key: str, default: str = "") -> str:
            return os.environ.get(key) or default

        return cls(
            base_url=env("BUS_BASE_URL").rstrip("/"),
            client_id=env("BUS_CLIENT_ID"),
            client_secret=env("BUS_CLIENT_SECRET"),
            pending_topic=env("BUS_PENDING_TOPIC", "brain.pending"),
            approval_topic=env("BUS_APPROVAL_TOPIC", "brain.approval"),
            timeout=float(env("BUS_TIMEOUT", "5") or 5),
        )


class BusClient:
    """极简总线发布客户端。

    只实现 `publish`。本服务作为**生产方**存在，不需要 pull/ack：
    待确认请求是"通知人去看"，不是需要本服务消费的任务队列。
    """

    def __init__(self, cfg: BusConfig) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self.published = 0
        self.last_error: str | None = None
        self.last_published_at: float | None = None

        if cfg.enabled:
            log.info("总线已启用：%s（client=%s, topic=%s）",
                     cfg.base_url, cfg.client_id, cfg.pending_topic)
        else:
            log.info("总线未配置，待确认请求不会上报（仅本地展示）")

    # ── 发布 ──────────────────────────────────────────────────

    def publish_pending(self, payload: dict[str, Any]) -> bool:
        """发布一条待确认请求。失败返回 False，绝不抛异常。"""
        return self._publish(self.cfg.pending_topic, "brain.approval_request", payload)

    def publish_resolved(self, payload: dict[str, Any]) -> bool:
        """发布"已处理"结果（确认/拒绝），用于审计留痕。"""
        return self._publish(self.cfg.approval_topic, "brain.approval_result", payload)

    def _publish(self, topic: str, msg_type: str, payload: dict[str, Any]) -> bool:
        if not self.cfg.enabled:
            return False

        body = json.dumps(
            {"topic": topic, "type": msg_type, "payload": payload},
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{self.cfg.base_url}/api/bus/publish",
            data=body,
            headers={
                "Content-Type": "application/json",
                # 后端 requireClient 解析的就是这个格式
                "Authorization": f"Bearer {self.cfg.client_id}.{self.cfg.client_secret}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                if 200 <= resp.status < 300:
                    with self._lock:
                        self.published += 1
                        self.last_error = None
                        import time
                        self.last_published_at = time.time()
                    log.debug("总线已发布 %s", topic)
                    return True
                self.last_error = f"HTTP {resp.status}"
                log.warning("总线发布失败（%s）：HTTP %s", topic, resp.status)
                return False
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            self.last_error = f"HTTP {exc.code} {detail}"
            log.warning("总线发布被拒（%s）：%s %s", topic, exc.code, detail)
            return False
        except Exception as exc:
            # 网络不通、DNS 失败等：不能影响主链路，只记日志
            self.last_error = str(exc)
            log.warning("总线不可达（%s）：%s", topic, exc)
            return False

    # ── 观测 ──────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.cfg.enabled,
                "baseUrl": self.cfg.base_url or None,
                "clientId": self.cfg.client_id or None,
                "pendingTopic": self.cfg.pending_topic,
                "approvalTopic": self.cfg.approval_topic,
                "published": self.published,
                "lastPublishedAt": self.last_published_at,
                "lastError": self.last_error,
            }
