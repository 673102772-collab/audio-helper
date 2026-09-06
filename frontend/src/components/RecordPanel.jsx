import { useEffect, useRef, useState } from "react";
import {
  MAX_DURATION_MS,
  extensionForMime,
  isDurationAllowed,
  isSizeAllowed,
  pickSupportedAudioType,
} from "../audio/format.js";
import { stopMediaStream } from "../audio/stream.js";

function microphoneErrorMessage(error) {
  if (!error) {
    return "录音失败，请重试";
  }
  if (error.name === "NotAllowedError" || error.name === "PermissionDeniedError") {
    return "无法使用麦克风，请在浏览器中允许麦克风权限后重试";
  }
  if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
    return "未找到可用的麦克风";
  }
  return "录音失败，请重试";
}

function formatDuration(durationMs) {
  return `${(durationMs / 1000).toFixed(1)} 秒`;
}

function formatSize(byteLength) {
  if (byteLength < 1024) {
    return `${byteLength} B`;
  }
  return `${(byteLength / 1024).toFixed(1)} KB`;
}

export default function RecordPanel({ onRoundStart, onClipReady, busy = false }) {
  const [phase, setPhase] = useState("idle");
  const [message, setMessage] = useState("");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [clip, setClip] = useState(null);

  const sessionRef = useRef(null);
  const clipUrlRef = useRef(null);

  function clearClipUrl() {
    if (clipUrlRef.current) {
      URL.revokeObjectURL(clipUrlRef.current);
      clipUrlRef.current = null;
    }
  }

  function detachSessionListeners(session) {
    if (!session) {
      return;
    }
    window.clearTimeout(session.maxTimer);
    window.clearInterval(session.elapsedTimer);
    if (session.removeListeners) {
      session.removeListeners();
      session.removeListeners = null;
    }
  }

  function releaseSessionResources(session) {
    if (!session) {
      return;
    }
    detachSessionListeners(session);
    stopMediaStream(session.stream);
    session.stream = null;
  }

  useEffect(() => {
    return () => {
      const session = sessionRef.current;
      if (session?.recorder && session.recorder.state !== "inactive") {
        session.closedByError = true;
        session.keepResult = false;
        try {
          session.recorder.stop();
        } catch {
          releaseSessionResources(session);
        }
      } else {
        releaseSessionResources(session);
      }
      sessionRef.current = null;
      clearClipUrl();
    };
  }, []);

  function keepClip({ blob, mimeType, durationMs }) {
    clearClipUrl();
    const url = URL.createObjectURL(blob);
    clipUrlRef.current = url;
    setClip({
      url,
      mimeType,
      durationMs,
      size: blob.size,
      filename: `meetup-recording.${extensionForMime(mimeType)}`,
    });
    setPhase("ready");
    setMessage("录音完成，正在查找碰面地点");
    setElapsedMs(durationMs);
    onClipReady?.({
      blob,
      mimeType,
      durationMs,
      filename: `meetup-recording.${extensionForMime(mimeType)}`,
    });
  }

  function stopRecording(reason) {
    const session = sessionRef.current;
    if (!session) {
      return;
    }

    session.holding = false;
    if (reason === "cancel") {
      session.keepResult = false;
    }

    detachSessionListeners(session);

    if (session.recorder && session.recorder.state === "recording") {
      try {
        session.recorder.stop();
      } catch {
        session.closedByError = true;
        releaseSessionResources(session);
        sessionRef.current = null;
        setPhase("error");
        setMessage("录制失败，请重试");
        setElapsedMs(0);
      }
      return;
    }

    if (session.recorder) {
      return;
    }

    releaseSessionResources(session);
    sessionRef.current = null;
    setElapsedMs(0);
    if (reason === "cancel") {
      setPhase("idle");
      setMessage("已取消录音");
      return;
    }
    setPhase("idle");
    setMessage("请再次按住按钮开始录音");
  }

  async function startRecording(pointerId, button) {
    if (sessionRef.current) {
      return;
    }

    const mimeType = pickSupportedAudioType();
    if (!mimeType) {
      setPhase("error");
      setMessage("当前浏览器不支持 WebM/Opus 录音，请更换 Chrome 或 Edge 后重试");
      return;
    }

    clearClipUrl();
    setClip(null);
    setMessage("");
    setElapsedMs(0);
    setPhase("requesting");
    onRoundStart?.();

    const session = {
      pointerId,
      mimeType,
      holding: true,
      keepResult: true,
      closedByError: false,
      startedAt: 0,
      chunks: [],
      stream: null,
      recorder: null,
      maxTimer: 0,
      elapsedTimer: 0,
      removeListeners: null,
    };
    sessionRef.current = session;

    const onPointerUp = () => stopRecording("release");
    const onPointerCancel = () => stopRecording("cancel");
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        stopRecording("cancel");
      }
    };
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    window.addEventListener("keydown", onKeyDown);
    session.removeListeners = () => {
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      window.removeEventListener("keydown", onKeyDown);
    };

    try {
      button.setPointerCapture(pointerId);
    } catch {
      // Window listeners still end the recording if capture is unavailable.
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      if (sessionRef.current === session) {
        releaseSessionResources(session);
        sessionRef.current = null;
        setPhase("error");
        setMessage(microphoneErrorMessage(error));
        setElapsedMs(0);
      }
      return;
    }

    if (sessionRef.current !== session || !session.holding) {
      stopMediaStream(stream);
      if (sessionRef.current === session) {
        releaseSessionResources(session);
        sessionRef.current = null;
        setPhase("idle");
        setElapsedMs(0);
        setMessage(session.keepResult ? "请再次按住按钮开始录音" : "已取消录音");
      }
      return;
    }

    session.stream = stream;

    let recorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType });
    } catch (error) {
      releaseSessionResources(session);
      sessionRef.current = null;
      setPhase("error");
      setMessage(microphoneErrorMessage(error));
      setElapsedMs(0);
      return;
    }

    session.recorder = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        session.chunks.push(event.data);
      }
    };
    recorder.onerror = () => {
      session.closedByError = true;
      session.keepResult = false;
      releaseSessionResources(session);
      if (sessionRef.current === session) {
        sessionRef.current = null;
        setPhase("error");
        setMessage("录制失败，请重试");
        setElapsedMs(0);
      }
    };
    recorder.onstop = () => {
      releaseSessionResources(session);
      if (sessionRef.current === session) {
        sessionRef.current = null;
      }
      if (session.closedByError) {
        return;
      }
      if (!session.keepResult) {
        setPhase("idle");
        setMessage("已取消录音");
        setElapsedMs(0);
        return;
      }

      const durationMs = Math.min(Math.max(0, Date.now() - session.startedAt), MAX_DURATION_MS);
      const blob = new Blob(session.chunks, { type: session.mimeType });

      if (!isDurationAllowed(durationMs)) {
        setPhase("error");
        setMessage("录音过短，请按住按钮说完整句话后再松开");
        setElapsedMs(0);
        return;
      }
      if (!isSizeAllowed(blob.size)) {
        setPhase("error");
        setMessage("录音文件过大，请控制在 5 MB 以内后重试");
        setElapsedMs(0);
        return;
      }

      keepClip({ blob, mimeType: session.mimeType, durationMs });
    };

    try {
      recorder.start(250);
    } catch (error) {
      session.closedByError = true;
      releaseSessionResources(session);
      sessionRef.current = null;
      setPhase("error");
      setMessage(microphoneErrorMessage(error));
      setElapsedMs(0);
      return;
    }

    session.startedAt = Date.now();
    setPhase("recording");
    setMessage("正在录音，松开结束");

    session.elapsedTimer = window.setInterval(() => {
      setElapsedMs(Math.min(Date.now() - session.startedAt, MAX_DURATION_MS));
    }, 100);

    session.maxTimer = window.setTimeout(() => {
      stopRecording("timeout");
    }, MAX_DURATION_MS);
  }

  function onPointerDown(event) {
    if (event.button !== undefined && event.button !== 0) {
      return;
    }
    event.preventDefault();
    startRecording(event.pointerId, event.currentTarget);
  }

  const recording = phase === "recording";

  return (
    <section className="record-panel">
      <button
        type="button"
        className={recording ? "record-button recording" : "record-button"}
        onPointerDown={onPointerDown}
        onContextMenu={(event) => event.preventDefault()}
      >
        {recording ? "松开结束" : "按住说话"}
      </button>
      <p className="record-status" role="status">
        {recording
          ? `录音中 ${formatDuration(elapsedMs)} / 60.0 秒`
          : busy
            ? `${message || "正在处理，再次按住将开始新一轮"}`
            : message}
      </p>
      {clip ? (
        <div className="record-result">
          <audio controls src={clip.url} preload="metadata">
            浏览器无法播放这段录音
          </audio>
          <p className="note">
            {formatDuration(clip.durationMs)} · {formatSize(clip.size)} · {clip.mimeType}
          </p>
          <a className="download-link" href={clip.url} download={clip.filename}>
            下载本段录音
          </a>
        </div>
      ) : null}
    </section>
  );
}
