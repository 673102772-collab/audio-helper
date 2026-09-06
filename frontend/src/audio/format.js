export const MIN_DURATION_MS = 1000;
export const MAX_DURATION_MS = 60_000;
export const MAX_AUDIO_BYTES = 5 * 1024 * 1024;

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm;codecs=Opus",
  "audio/webm",
];

export function pickSupportedAudioType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return null;
  }
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

export function isDurationAllowed(durationMs) {
  return durationMs >= MIN_DURATION_MS && durationMs <= MAX_DURATION_MS;
}

export function isSizeAllowed(byteLength) {
  return byteLength > 0 && byteLength <= MAX_AUDIO_BYTES;
}

export function extensionForMime(mimeType) {
  if (mimeType && mimeType.includes("webm")) {
    return "webm";
  }
  return "webm";
}
