"""
本地语音识别服务（FunASR Paraformer-zh）。

启动：
    cd Software/reservoir-platform/speech-recognition && python asr_server.py

依赖：
    pip install funasr torch fastapi uvicorn python-multipart

端口：8001
接口：POST /asr  （multipart/form-data，字段名 file，WAV 16kHz 单声道）
      GET  /health

说明：模型首次加载约 900MB，CPU 推理；本服务只在内网使用，数据不出内网。
"""
from __future__ import annotations

import os
import tempfile
import wave
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# 单例模型容器，避免每次请求重复加载
_state: dict = {}


def _load_model():
    """懒加载 FunASR 模型；未安装依赖时给出明确提示而不是直接崩溃。"""
    if "model" in _state:
        return _state["model"]

    try:
        from funasr import AutoModel  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装 funasr，请先执行: pip install funasr torch"
        ) from exc

    print("[asr] 正在加载 paraformer-zh 模型（首次约 900MB，请耐心等待）...")
    model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        disable_update=True,
    )
    _state["model"] = model
    print("[asr] 模型加载完成")
    return model


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预热，避免首个请求超时
    try:
        _load_model()
        _state["ready"] = True
    except Exception as exc:  # pragma: no cover
        _state["ready"] = False
        _state["error"] = str(exc)
        print(f"[asr] 模型加载失败：{exc}")
    yield
    _state.clear()


app = FastAPI(title="水库数字人 - 本地语音识别服务", lifespan=lifespan)

# 仅内网使用，放开跨域便于调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 目标格式：16kHz 单声道 16bit
TARGET_SAMPLE_RATE = 16000


def _check_wav(path: str) -> tuple[int, int]:
    """返回 (采样率, 声道数)；非 WAV 时抛错。"""
    try:
        with wave.open(path, "rb") as wf:
            return wf.getframerate(), wf.getnchannels()
    except wave.Error as exc:
        raise HTTPException(status_code=400, detail=f"音频格式不支持，需要 WAV：{exc}") from exc


@app.get("/health")
def health():
    return {
        "status": "ok",
        "ready": bool(_state.get("ready")),
        "error": _state.get("error"),
    }


@app.post("/asr")
async def asr(file: UploadFile = File(...)):
    model = _state.get("model")
    if model is None:
        if _state.get("error"):
            raise HTTPException(status_code=503, detail=f"模型未就绪：{_state['error']}")
        model = _load_model()
        _state["model"] = model

    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    tmp_path = ""
    try:
        raw = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        rate, channels = _check_wav(tmp_path)
        if rate != TARGET_SAMPLE_RATE or channels != 1:
            print(f"[asr] 提示：收到 {rate}Hz / {channels}声道，期望 {TARGET_SAMPLE_RATE}Hz 单声道")

        result = model.generate(input=tmp_path, batch_size_s=300)
        text = ""
        if isinstance(result, list) and result:
            text = result[0].get("text", "") if isinstance(result[0], dict) else str(result[0])
        return {"text": text}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
