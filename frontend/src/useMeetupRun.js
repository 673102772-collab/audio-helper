import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiClientError,
  extractMeetup,
  fetchAudioBlob,
  finalizeSearch,
  getHealth,
  isAbortError,
  recognizeAudio,
  searchMeetup,
  uploadAudio,
} from "./api.js";

export const STAGE_LABELS = {
  checking: "正在检查服务",
  uploading: "上传中",
  recognizing: "识别中",
  extracting: "提取中",
  searching: "找店中",
  finalizing: "生成推荐中",
  playing: "正在加载语音",
  done: "完成",
};

function emptyResults() {
  return {
    audioId: null,
    asrText: "",
    extract: null,
    midpoint: null,
    pois: [],
    searchId: null,
    replyText: "",
    warning: "",
    ttsUrl: null,
    needsManualPlay: false,
  };
}

export function useMeetupRun() {
  const [health, setHealth] = useState("checking");
  const [healthMessage, setHealthMessage] = useState("正在检查后端服务…");
  const [stage, setStage] = useState("idle");
  const [error, setError] = useState(null);
  const [results, setResults] = useState(emptyResults);

  const runTokenRef = useRef(0);
  const abortRef = useRef(null);
  const ttsUrlRef = useRef(null);
  const audioRef = useRef(null);

  const stopAudio = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if (ttsUrlRef.current) {
      URL.revokeObjectURL(ttsUrlRef.current);
      ttsUrlRef.current = null;
    }
  }, []);

  const abortCurrent = useCallback(() => {
    runTokenRef.current += 1;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    stopAudio();
  }, [stopAudio]);

  const clearRound = useCallback(() => {
    abortCurrent();
    setStage("idle");
    setError(null);
    setResults(emptyResults());
  }, [abortCurrent]);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const data = await getHealth({ signal: controller.signal });
        if (controller.signal.aborted) {
          return;
        }
        if (data.status === "ok") {
          setHealth("ok");
          setHealthMessage("后端服务正常");
        } else {
          setHealth("down");
          setHealthMessage("后端服务不可用，请确认已启动");
        }
      } catch (caught) {
        if (isAbortError(caught) || controller.signal.aborted) {
          return;
        }
        setHealth("down");
        setHealthMessage(caught instanceof ApiClientError ? caught.message : "无法连接后端服务");
      }
    })();
    return () => {
      controller.abort();
    };
  }, []);

  useEffect(() => {
    return () => {
      abortCurrent();
    };
  }, [abortCurrent]);

  useEffect(() => {
    const url = results.ttsUrl;
    const audio = audioRef.current;
    if (!url || !audio) {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await audio.play();
        if (!cancelled) {
          setResults((current) => ({ ...current, needsManualPlay: false }));
        }
      } catch (caught) {
        if (cancelled) {
          return;
        }
        if (caught?.name === "NotAllowedError") {
          setResults((current) => ({
            ...current,
            needsManualPlay: true,
            warning: current.warning || "浏览器拦截了自动播放，请点击播放",
          }));
          return;
        }
        setResults((current) => ({
          ...current,
          needsManualPlay: false,
          warning: "语音加载失败，请阅读文字结果",
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [results.ttsUrl]);

  const playManually = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio?.src) {
      return;
    }
    try {
      await audio.play();
      setResults((current) => ({ ...current, needsManualPlay: false }));
    } catch {
      setResults((current) => ({
        ...current,
        needsManualPlay: true,
        warning: current.warning || "浏览器拦截了自动播放，请点击播放",
      }));
    }
  }, []);

  const start = useCallback(
    async (clip, city) => {
      abortCurrent();
      const token = runTokenRef.current;
      const controller = new AbortController();
      abortRef.current = controller;
      const signal = controller.signal;

      setError(null);
      setResults(emptyResults());
      setStage("checking");

      const stillCurrent = () => runTokenRef.current === token && !signal.aborted;

      try {
        const healthData = await getHealth({ signal });
        if (!stillCurrent()) {
          return;
        }
        if (healthData.status !== "ok") {
          throw new ApiClientError({
            code: "SERVICE_UNAVAILABLE",
            message: "后端服务不可用，请确认已启动",
            stage: "request",
          });
        }
        setHealth("ok");
        setHealthMessage("后端服务正常");

        setStage("uploading");
        const uploaded = await uploadAudio(clip.blob, clip.filename, { signal });
        if (!stillCurrent()) {
          return;
        }
        setResults((current) => ({ ...current, audioId: uploaded.audio_id }));

        setStage("recognizing");
        const asr = await recognizeAudio(uploaded.audio_id, { signal });
        if (!stillCurrent()) {
          return;
        }
        setResults((current) => ({ ...current, asrText: asr.text }));

        setStage("extracting");
        const extracted = await extractMeetup(asr.text, city, { signal });
        if (!stillCurrent()) {
          return;
        }
        setResults((current) => ({ ...current, extract: extracted }));

        setStage("searching");
        const searched = await searchMeetup(extracted, { signal });
        if (!stillCurrent()) {
          return;
        }
        setResults((current) => ({
          ...current,
          searchId: searched.search_id,
          midpoint: searched.midpoint,
          pois: Array.isArray(searched.pois) ? searched.pois : [],
        }));

        setStage("finalizing");
        const finalized = await finalizeSearch(searched.search_id, { signal });
        if (!stillCurrent()) {
          return;
        }

        const replyText = finalized.reply_text || "";
        const warning = finalized.warning || "";
        setResults((current) => ({
          ...current,
          replyText,
          warning,
        }));

        if (!finalized.audio_url) {
          setStage("done");
          setResults((current) => ({
            ...current,
            warning: warning || "语音合成服务暂时不可用，请阅读文字结果",
          }));
          return;
        }

        setStage("playing");
        try {
          const blob = await fetchAudioBlob(finalized.audio_url, { signal });
          if (!stillCurrent()) {
            return;
          }
          stopAudio();
          const objectUrl = URL.createObjectURL(blob);
          ttsUrlRef.current = objectUrl;
          if (!stillCurrent()) {
            URL.revokeObjectURL(objectUrl);
            ttsUrlRef.current = null;
            return;
          }
          setResults((current) => ({
            ...current,
            ttsUrl: objectUrl,
            needsManualPlay: false,
          }));
          setStage("done");
        } catch (audioError) {
          if (isAbortError(audioError) || !stillCurrent()) {
            return;
          }
          const message =
            audioError instanceof ApiClientError
              ? audioError.message
              : "语音加载失败，请阅读文字结果";
          setResults((current) => ({
            ...current,
            warning: message,
            ttsUrl: null,
            needsManualPlay: false,
          }));
          setStage("done");
        }
      } catch (caught) {
        if (isAbortError(caught) || !stillCurrent()) {
          return;
        }
        const normalized =
          caught instanceof ApiClientError
            ? caught
            : new ApiClientError({ message: "请求失败，请稍后重试" });
        setError(normalized);
        setStage("error");
      }
    },
    [abortCurrent, stopAudio],
  );

  return {
    health,
    healthMessage,
    stage,
    error,
    results,
    audioRef,
    busy: stage !== "idle" && stage !== "done" && stage !== "error",
    clearRound,
    start,
    playManually,
  };
}
