import axios from "axios";

export const api = axios.create({
  baseURL: "http://localhost:8003",
});

export const TIMEOUTS = {
  health: 8_000,
  upload: 12_000,
  asr: 40_000,
  extract: 22_000,
  search: 35_000,
  finalize: 52_000,
  audio: 15_000,
};

export class ApiClientError extends Error {
  constructor({ code, message, stage, status } = {}) {
    super(message || "请求失败，请稍后重试");
    this.name = "ApiClientError";
    this.code = code || "REQUEST_FAILED";
    this.stage = stage || "request";
    this.status = status ?? null;
  }
}

export function isAbortError(error) {
  return (
    axios.isCancel(error) ||
    error?.code === "ERR_CANCELED" ||
    error?.name === "CanceledError" ||
    error?.name === "AbortError"
  );
}

function fallbackNetworkMessage(error) {
  if (error?.code === "ECONNABORTED" || String(error?.message || "").toLowerCase().includes("timeout")) {
    return "请求超时，请稍后重试";
  }
  return "网络连接失败，请检查网络后重试";
}

async function readErrorPayload(error) {
  const data = error?.response?.data;
  if (!data) {
    return null;
  }
  if (data instanceof Blob) {
    const text = await data.text();
    if (!text) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }
  if (typeof data === "string") {
    try {
      return JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (typeof data === "object") {
    return data;
  }
  return null;
}

export async function normalizeError(error, stage = "request") {
  if (isAbortError(error) || error instanceof ApiClientError) {
    return error;
  }
  const payload = await readErrorPayload(error);
  const detail = payload?.error;
  if (detail && typeof detail === "object") {
    return new ApiClientError({
      code: detail.code,
      message: detail.message || "请求失败，请稍后重试",
      stage: detail.stage || stage,
      status: error.response?.status,
    });
  }
  if (!error?.response) {
    return new ApiClientError({
      code: error?.code === "ECONNABORTED" ? "TIMEOUT" : "NETWORK_ERROR",
      message: fallbackNetworkMessage(error),
      stage,
    });
  }
  return new ApiClientError({
    code: "REQUEST_FAILED",
    message: "请求失败，请稍后重试",
    stage,
    status: error.response.status,
  });
}

function unwrapData(payload, stage) {
  if (!payload || typeof payload !== "object" || payload.data == null) {
    throw new ApiClientError({
      code: "INVALID_RESPONSE",
      message: "服务返回异常，请稍后重试",
      stage,
    });
  }
  return {
    request_id: payload.request_id,
    data: payload.data,
  };
}

async function requestJson(config, stage) {
  try {
    const response = await api.request(config);
    return unwrapData(response.data, stage);
  } catch (error) {
    throw await normalizeError(error, stage);
  }
}

export async function getHealth({ signal } = {}) {
  const { data } = await requestJson(
    {
      method: "GET",
      url: "/health",
      timeout: TIMEOUTS.health,
      signal,
    },
    "request",
  );
  return data;
}

export async function uploadAudio(blob, filename, { signal } = {}) {
  const form = new FormData();
  form.append("file", blob, filename);
  const { data } = await requestJson(
    {
      method: "POST",
      url: "/upload",
      data: form,
      timeout: TIMEOUTS.upload,
      signal,
    },
    "upload",
  );
  return data;
}

export async function recognizeAudio(audioId, { signal } = {}) {
  const { data } = await requestJson(
    {
      method: "POST",
      url: "/asr",
      data: { audio_id: audioId },
      timeout: TIMEOUTS.asr,
      signal,
    },
    "asr",
  );
  return data;
}

export async function extractMeetup(text, city, { signal } = {}) {
  const { data } = await requestJson(
    {
      method: "POST",
      url: "/extract",
      data: { text, city },
      timeout: TIMEOUTS.extract,
      signal,
    },
    "extract",
  );
  return data;
}

export async function searchMeetup(fields, { signal } = {}) {
  const { data } = await requestJson(
    {
      method: "POST",
      url: "/search",
      data: {
        city_a: fields.city_a,
        address_a: fields.address_a,
        city_b: fields.city_b,
        address_b: fields.address_b,
        category: fields.category,
      },
      timeout: TIMEOUTS.search,
      signal,
    },
    "search",
  );
  return data;
}

export async function finalizeSearch(searchId, { signal } = {}) {
  const { data } = await requestJson(
    {
      method: "POST",
      url: "/finalize",
      data: { search_id: searchId },
      timeout: TIMEOUTS.finalize,
      signal,
    },
    "finalize",
  );
  return data;
}

export async function fetchAudioBlob(audioUrl, { signal } = {}) {
  try {
    const response = await api.get(audioUrl, {
      responseType: "blob",
      timeout: TIMEOUTS.audio,
      signal,
      validateStatus: () => true,
    });
    const contentType = String(response.headers["content-type"] || "");
    if (response.status >= 400 || contentType.includes("application/json")) {
      const fakeError = { response: { data: response.data, status: response.status } };
      throw await normalizeError(fakeError, "audio_download");
    }
    if (!(response.data instanceof Blob) || response.data.size === 0) {
      throw new ApiClientError({
        code: "AUDIO_NOT_FOUND",
        message: "语音文件不存在或已过期",
        stage: "audio_download",
        status: response.status,
      });
    }
    return response.data;
  } catch (error) {
    throw await normalizeError(error, "audio_download");
  }
}
