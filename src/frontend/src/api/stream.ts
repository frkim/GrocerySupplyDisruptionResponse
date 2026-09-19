import type { StreamEvent } from '../types';

/**
 * The run stream is a POST, so `EventSource` is unusable. We read the raw body
 * and reassemble SSE frames by hand — JSON payloads are routinely split across
 * network chunks, so frame boundaries must be tracked in a persistent buffer.
 */
export async function* streamRun(
  signal?: AbortSignal,
  endpoint = '/api/runs/stream',
): AsyncGenerator<StreamEvent, void, void> {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({}),
    ...(signal ? { signal } : {}),
  });

  if (!response.ok) {
    const detail = await safeText(response);
    throw new Error(
      `Run stream failed: ${response.status} ${response.statusText}${detail ? ` — ${detail}` : ''}`,
    );
  }
  if (!response.body) {
    throw new Error('Run stream failed: the response carried no readable body.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n');

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseFrame(frame);
        if (event) yield event;
        boundary = buffer.indexOf('\n\n');
      }
    }

    // Flush anything the decoder still holds plus a trailing unterminated frame.
    buffer += decoder.decode();
    buffer = buffer.replace(/\r\n/g, '\n');
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* the stream may already be closed; nothing useful to do */
    }
  }
}

/** Extract and parse the `data:` payload of one SSE frame. */
function parseFrame(frame: string): StreamEvent | null {
  const trimmed = frame.trim();
  if (!trimmed) return null;

  const payload = trimmed
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n')
    .trim();

  const raw = payload || (trimmed.startsWith('{') ? trimmed : '');
  if (!raw) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && typeof (parsed as { type?: unknown }).type === 'string') {
      return parsed as StreamEvent;
    }
  } catch {
    /* Malformed or partial frame — drop it rather than tearing down the run. */
  }
  return null;
}

async function safeText(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text.slice(0, 240);
  } catch {
    return '';
  }
}
