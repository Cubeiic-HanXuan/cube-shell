"""
语音输入模块。

提供麦克风录音和语音识别功能。
使用 QMediaRecorder 录音（macOS 原生兼容），然后通过 ffmpeg 转换为标准 WAV 格式，
确保输出格式被智谱 GLM-ASR-2512 API 正确识别。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import traceback

from PySide6.QtCore import QThread, Signal, QUrl, QObject, QTimer
from PySide6.QtMultimedia import (
    QMediaCaptureSession, QAudioInput, QMediaRecorder,
    QMediaFormat,
)

from function import util


class _SpeechRecognitionThread(QThread):
    """语音识别工作线程。
    
    先用 ffmpeg 将录音文件转为标准 16kHz/16bit/Mono WAV，再调用智谱 GLM-ASR-2512。
    """

    recognized = Signal(str)   # 识别成功，返回文本
    error = Signal(str)        # 识别失败

    def __init__(self, audio_path: str, language: str = "zh-CN", parent=None):
        super().__init__(parent)
        self._audio_path = audio_path
        self._language = language

    def run(self):
        wav_path = None
        try:
            # Step 1: 用 ffmpeg 转换为标准 WAV（16kHz, 16bit, Mono）
            wav_path = self._convert_to_wav()
            if not wav_path:
                self.error.emit("音频格式转换失败")
                return

            # Step 2: 调用智谱 API
            from zai import ZhipuAiClient
            from .secrets import get_ai_api_key

            api_key = get_ai_api_key()
            if not api_key:
                self.error.emit("未配置 API Key，请在「设置 -> AI 设置」中配置")
                return

            client = ZhipuAiClient(api_key=api_key)

            with open(wav_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="glm-asr-2512",
                    file=audio_file,
                    stream=False,
                )

            # 兼容多种响应格式
            text = None
            if hasattr(response, 'text') and response.text:
                text = response.text
            elif hasattr(response, 'choices') and response.choices:
                text = response.choices[0].message.content

            if text:
                self.recognized.emit(text.strip())
            else:
                self.recognized.emit("")

        except ImportError:
            self.error.emit("请先安装 zai-sdk: pip install zai-sdk")
        except Exception as e:
            util.logger.error(f"语音识别失败: {e}\n{traceback.format_exc()}")
            err_msg = str(e)
            if "api_key" in err_msg.lower() or "unauthorized" in err_msg.lower() or "401" in err_msg:
                self.error.emit("API Key 无效或已过期，请更新配置")
            elif "timeout" in err_msg.lower():
                self.error.emit("网络请求超时，请检查网络连接")
            elif "too large" in err_msg.lower() or "413" in err_msg:
                self.error.emit("音频文件过大，请录制不超过 30 秒")
            else:
                self.error.emit(f"语音识别失败: {err_msg}")
        finally:
            # 清理转换后的 WAV 文件
            if wav_path and os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

    def _convert_to_wav(self) -> str | None:
        """将录音文件转为标准 WAV 格式。
        
        macOS: 使用系统自带 afconvert（每台 Mac 都有，无需安装）
        Windows/Linux: 直接录为 WAV，无需转换（返回原文件）
        """
        if not os.path.exists(self._audio_path):
            return None

        # 文件太小则跳过
        if os.path.getsize(self._audio_path) < 512:
            return None

        import sys
        if sys.platform == "darwin":
            # macOS: M4A → afconvert → 标准 WAV
            wav_path = self._audio_path.rsplit(".", 1)[0] + "_converted.wav"
            return self._convert_with_afconvert(wav_path)
        else:
            # Windows/Linux: 直接录的就是 WAV，直接用
            return self._audio_path

    def _convert_with_afconvert(self, wav_path: str) -> str | None:
        """macOS 系统自带的 afconvert 转换工具（/usr/bin/afconvert，无需安装）。"""
        try:
            result = subprocess.run(
                [
                    "/usr/bin/afconvert",
                    "-f", "WAVE",        # 输出 WAV 格式
                    "-d", "LEI16@16000",  # 16-bit Little-Endian Integer, 16kHz
                    "-c", "1",            # 单声道
                    self._audio_path,
                    wav_path
                ],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0 and os.path.exists(wav_path):
                return wav_path
            else:
                util.logger.error(f"afconvert 转换失败: {result.stderr.decode(errors='ignore')[:200]}")
                return None
        except Exception as e:
            util.logger.error(f"afconvert 转换异常: {e}")
            return None


class VoiceInputManager(QObject):
    """语音输入管理器，支持实时转文字模式。

    使用 QMediaRecorder 录音 + 系统自带工具转换 + 智谱 API 识别。
    录音过程中每隔数秒自动分段，通过 recorderStateChanged 确保文件完整后再处理。

    信号:
        recording_started: 开始录音
        recording_stopped: 停止录音
        recognition_started: 开始识别
        partial_text_recognized: 实时累积文字更新 (str)
        text_recognized: 最终完整识别结果 (str)
        error_occurred: 错误 (str)
    """

    recording_started = Signal()
    recording_stopped = Signal()
    recognition_started = Signal()
    partial_text_recognized = Signal(str)  # 实时增量
    text_recognized = Signal(str)          # 最终结果
    error_occurred = Signal(str)

    # 分段间隔（毫秒）
    CHUNK_INTERVAL_MS = 5000

    # 内部状态
    _STATE_IDLE = 0
    _STATE_RECORDING = 1
    _STATE_STOPPING_FOR_NEXT_CHUNK = 2
    _STATE_STOPPING_FINAL = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._STATE_IDLE
        self._current_chunk_path: str | None = None
        self._accumulated_text = ""
        self._pending_chunks = 0
        self._recognition_threads: list[_SpeechRecognitionThread] = []

        # Qt Multimedia 组件（延迟初始化）
        self._capture_session = None
        self._audio_input = None
        self._recorder = None

        # 分段定时器
        self._chunk_timer = QTimer(self)
        self._chunk_timer.setInterval(self.CHUNK_INTERVAL_MS)
        self._chunk_timer.timeout.connect(self._on_chunk_timeout)

    def _ensure_recorder(self) -> bool:
        """确保录音组件已初始化。"""
        if self._capture_session is not None:
            return True

        try:
            from PySide6.QtMultimedia import QMediaDevices
            import sys

            devices = QMediaDevices.audioInputs()
            if not devices:
                self.error_occurred.emit("未检测到麦克风设备")
                return False

            self._audio_input = QAudioInput()
            self._capture_session = QMediaCaptureSession()
            self._recorder = QMediaRecorder()

            self._capture_session.setAudioInput(self._audio_input)
            self._capture_session.setRecorder(self._recorder)

            # 根据平台选择录音格式
            fmt = QMediaFormat()
            if sys.platform == "darwin":
                # macOS: 录 M4A（原生支持最好），后续用 afconvert 转 WAV
                fmt.setFileFormat(QMediaFormat.FileFormat.MPEG4)
                fmt.setAudioCodec(QMediaFormat.AudioCodec.AAC)
            else:
                # Windows/Linux: 直接录 WAV（PCM），无需转换
                fmt.setFileFormat(QMediaFormat.FileFormat.Wave)
            self._recorder.setMediaFormat(fmt)

            # 核心：监听状态变化（stop() 是异步的）
            self._recorder.recorderStateChanged.connect(self._on_recorder_state_changed)
            self._recorder.errorOccurred.connect(self._on_recorder_error)

            return True

        except Exception as e:
            self.error_occurred.emit(f"初始化录音设备失败: {e}")
            return False

    @property
    def is_recording(self) -> bool:
        return self._state != self._STATE_IDLE

    def toggle_recording(self):
        """切换录音状态。"""
        if self._state != self._STATE_IDLE:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """开始录音（实时模式）。"""
        if self._state != self._STATE_IDLE:
            return

        if not self._ensure_recorder():
            return

        # 重置状态
        self._accumulated_text = ""
        self._pending_chunks = 0

        # 开始第一段录音
        self._start_new_chunk()
        self._state = self._STATE_RECORDING
        self._chunk_timer.start()
        self.recording_started.emit()

    def stop_recording(self):
        """停止录音。"""
        if self._state == self._STATE_IDLE:
            return

        self._chunk_timer.stop()
        self._state = self._STATE_STOPPING_FINAL
        self.recording_stopped.emit()
        self._recorder.stop()

    def _start_new_chunk(self):
        """开始新的一段录音。"""
        import sys
        ext = ".m4a" if sys.platform == "darwin" else ".wav"
        tmp = tempfile.NamedTemporaryFile(
            suffix=ext, delete=False, prefix="cube_voice_"
        )
        self._current_chunk_path = tmp.name
        tmp.close()

        self._recorder.setOutputLocation(QUrl.fromLocalFile(self._current_chunk_path))
        self._recorder.record()

    def _on_chunk_timeout(self):
        """定时器触发：停止当前段，等状态回调中处理。"""
        if self._state != self._STATE_RECORDING:
            return

        self._state = self._STATE_STOPPING_FOR_NEXT_CHUNK
        self._recorder.stop()

    def _on_recorder_state_changed(self, state):
        """录音器状态变化 - 文件写入完成后再处理。"""
        if state != QMediaRecorder.RecorderState.StoppedState:
            return

        finished_path = self._current_chunk_path
        self._current_chunk_path = None

        if self._state == self._STATE_STOPPING_FOR_NEXT_CHUNK:
            # 分段完成 → 开始新段 → 发送识别
            self._state = self._STATE_RECORDING
            self._start_new_chunk()
            if finished_path and os.path.exists(finished_path):
                self._start_chunk_recognition(finished_path)

        elif self._state == self._STATE_STOPPING_FINAL:
            # 最终段 → 发送识别 → 等待完成
            self._state = self._STATE_IDLE
            if finished_path and os.path.exists(finished_path):
                self._start_chunk_recognition(finished_path)
            else:
                self._try_finalize()

    def _start_chunk_recognition(self, audio_path: str):
        """启动识别线程（内含 ffmpeg 转换）。"""
        self._pending_chunks += 1
        self.recognition_started.emit()

        thread = _SpeechRecognitionThread(
            audio_path=audio_path,
            language="zh-CN",
            parent=self,
        )
        thread.recognized.connect(self._on_chunk_recognized)
        thread.error.connect(self._on_recognition_error)
        thread.finished.connect(lambda p=audio_path: self._on_chunk_finished(p))
        self._recognition_threads.append(thread)
        thread.start()

    # 智谱 API 在无语音/静音时会返回这些占位符，需过滤
    _SILENCE_MARKERS = {"#", "##", "###", "...", "。", ""}

    def _on_chunk_recognized(self, text: str):
        """单段识别完成。"""
        if text and text.strip() not in self._SILENCE_MARKERS:
            self._accumulated_text += text
            self.partial_text_recognized.emit(self._accumulated_text)

    def _on_chunk_finished(self, audio_path: str):
        """单段线程结束。"""
        self._pending_chunks -= 1
        self._cleanup_temp(audio_path)
        self._recognition_threads = [t for t in self._recognition_threads if t.isRunning()]
        self._try_finalize()

    def _try_finalize(self):
        """所有段识别完毕时发送最终结果。"""
        if self._state == self._STATE_IDLE and self._pending_chunks <= 0:
            if self._accumulated_text:
                self.text_recognized.emit(self._accumulated_text)
            else:
                self.text_recognized.emit("")

    def _on_recognition_error(self, error_msg: str):
        """识别失败。"""
        self.error_occurred.emit(error_msg)

    def _on_recorder_error(self, error, error_string):
        """录音器错误。"""
        self._chunk_timer.stop()
        self._state = self._STATE_IDLE
        self.recording_stopped.emit()
        self.error_occurred.emit(f"录音错误: {error_string}")

    def _cleanup_temp(self, path: str):
        """清理临时文件。"""
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass
