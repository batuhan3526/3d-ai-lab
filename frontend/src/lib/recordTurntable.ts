// Task E1 / F1: client-side turntable video capture via MediaRecorder.
//
// The R3F <canvas> is already spinning (TurntableGroup useFrame, see
// ThreeCanvas.tsx). We grab a MediaStream from it with canvas.captureStream(fps)
// and record for the duration of `turns` full revolutions, then resolve a webm
// Blob. No server round-trip, no GPU work — purely the browser encoding what is
// on screen.
//
// Task A: webm is not playable everywhere (iOS/QuickTime, many social apps).
// After recording we offer an H.264 mp4 by POSTing the webm to the gateway
// (`/convert/video`, ffmpeg). If ffmpeg is missing the endpoint returns 422 and
// the caller falls back to downloading the raw webm.
//
// F1: rotation is now TIME-BASED and FPS-INDEPENDENT. TurntableGroup advances
// rotation.y by (2π / secondsPerTurn) * delta every frame, so one full turn
// always takes exactly `secondsPerTurn` seconds regardless of render FPS. The
// caller MUST pass the SAME secondsPerTurn used by the live scene so the
// recording duration (turns × secondsPerTurn) captures exactly `turns` full
// revolutions — no more, no less.

import { useAuth } from "../store/auth";

/** Default seconds per full revolution (matches DesignerPage turntable default). */
export const SECONDS_PER_TURN = 12;

export interface RecordTurntableOptions {
  turns?: 1 | 2;
  fps?: number;
  /** Seconds per full revolution; MUST match the live scene's turntable speed. */
  secondsPerTurn?: number;
}

// Codec fallback chain: prefer vp9, fall back to vp8, then bare webm.
function pickMimeType(): string {
  const candidates = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  const supported = (c: string) =>
    typeof MediaRecorder !== "undefined" &&
    typeof MediaRecorder.isTypeSupported === "function" &&
    MediaRecorder.isTypeSupported(c);
  for (const c of candidates) {
    if (supported(c)) return c;
  }
  return "video/webm";
}

/**
 * Record the turntable animation currently playing on `canvas`.
 * Resolves a webm Blob once `turns` revolutions have elapsed.
 */
export function recordTurntable(
  canvas: HTMLCanvasElement,
  opts: RecordTurntableOptions = {},
): Promise<Blob> {
  const turns = opts.turns ?? 1;
  const fps = opts.fps ?? 30;
  const secondsPerTurn = opts.secondsPerTurn ?? SECONDS_PER_TURN;
  const durationMs = Math.max(1, Math.round(turns * secondsPerTurn * 1000));

  return new Promise<Blob>((resolve, reject) => {
    if (!canvas || typeof canvas.captureStream !== "function") {
      reject(new Error("Canvas captureStream is not supported in this browser"));
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      reject(new Error("MediaRecorder is not supported in this browser"));
      return;
    }

    let stream: MediaStream;
    try {
      stream = canvas.captureStream(fps);
    } catch (err) {
      reject(err instanceof Error ? err : new Error(String(err)));
      return;
    }

    const mimeType = pickMimeType();
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType });
    } catch (err) {
      stream.getTracks().forEach((tr) => tr.stop());
      reject(err instanceof Error ? err : new Error(String(err)));
      return;
    }

    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    recorder.onerror = (e) => {
      stream.getTracks().forEach((tr) => tr.stop());
      const err = (e as unknown as { error?: DOMException }).error;
      reject(err ?? new Error("MediaRecorder error"));
    };
    recorder.onstop = () => {
      stream.getTracks().forEach((tr) => tr.stop());
      resolve(new Blob(chunks, { type: mimeType.split(";")[0] }));
    };

    recorder.start();
    setTimeout(() => {
      if (recorder.state !== "inactive") recorder.stop();
    }, durationMs);
  });
}

/** Thrown when the gateway cannot convert the webm (e.g. ffmpeg missing → 422). */
export class ConvertUnavailableError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ConvertUnavailableError";
  }
}

/**
 * Convert a recorded webm Blob to an mp4 Blob via the gateway (`/convert/video`,
 * ffmpeg). Rejects with {@link ConvertUnavailableError} when the server has no
 * ffmpeg (HTTP 422) so callers can fall back to the raw webm download.
 */
export async function convertTurntableToMp4(webm: Blob): Promise<Blob> {
  const form = new FormData();
  form.append("file", webm, "turntable.webm");
  const token = useAuth.getState().token;
  const resp = await fetch("/api/convert/video", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) {
    throw new ConvertUnavailableError(
      resp.status,
      `mp4 dönüştürme başarısız: HTTP ${resp.status}`,
    );
  }
  return resp.blob();
}

/** Trigger a browser download of a recorded turntable Blob. */
export function downloadBlob(blob: Blob, filename = "turntable.webm"): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
