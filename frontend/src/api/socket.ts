/**
 * WS 구독 + 지수 백오프 재연결.
 *
 * **재연결 성공 시 반드시 스냅샷을 재조회해야 한다.** 이벤트만 이어받으면 끊긴 동안의
 * 변경이 영구히 유실된다 — 그래서 `onReconnect` 콜백이 선택이 아니라 필수 인자다.
 */

import type { OfficeEvent } from './types';

const WS_PATH = '/api/v1/ws/office';
const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 15_000;

export interface SocketHandlers {
  readonly onEvent: (event: OfficeEvent) => void;
  /** 재연결이 성립한 직후 호출된다. 여기서 스냅샷을 다시 받아 상태를 맞춘다. */
  readonly onReconnect: () => void;
  readonly onStatusChange?: (connected: boolean) => void;
}

/** 지수 백오프에 지터를 섞는다. 서버 재시작 시 모든 탭이 같은 순간에 몰리지 않게. */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const exponential = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return Math.round(exponential * (0.5 + random() * 0.5));
}

export function connectOfficeSocket(handlers: SocketHandlers): () => void {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let timer: number | undefined;
  let closed = false;
  let everConnected = false;

  const open = (): void => {
    const url = new URL(WS_PATH, window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(url);

    socket.addEventListener('open', () => {
      handlers.onStatusChange?.(true);
      // 첫 연결에서는 main이 이미 스냅샷을 받았다. 재연결일 때만 다시 맞춘다.
      if (everConnected) handlers.onReconnect();
      everConnected = true;
      attempt = 0;
    });

    socket.addEventListener('message', (message: MessageEvent<string>) => {
      handlers.onEvent(JSON.parse(message.data) as OfficeEvent);
    });

    socket.addEventListener('close', () => {
      handlers.onStatusChange?.(false);
      if (closed) return;
      timer = window.setTimeout(open, backoffDelay(attempt));
      attempt += 1;
    });
  };

  open();

  return () => {
    closed = true;
    window.clearTimeout(timer);
    socket?.close();
  };
}
