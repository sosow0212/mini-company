/**
 * fetch 래퍼.
 *
 * 개발 서버와 nginx가 `/api`를 백엔드로 프록시하므로 브라우저 기준 동일 출처다.
 * 그래서 절대 URL도, CORS도 필요 없다.
 */

import type { Activity, CursorPage, OfficeSnapshot } from './types';

const API = '/api/v1';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(`API ${status} (${code})`);
    this.name = 'ApiError';
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorCode(response));
  }
  return (await response.json()) as T;
}

async function readErrorCode(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === 'object' && 'code' in body) {
      return String((body as { code: unknown }).code);
    }
  } catch {
    // 본문이 JSON이 아니면 상태코드만으로 충분하다.
  }
  return 'unknown';
}

/** 진입 시 1회, WS 재연결 직후 1회. 이 두 시점 외에는 부르지 않는다. */
export function fetchSnapshot(): Promise<OfficeSnapshot> {
  return get<OfficeSnapshot>('/office/snapshot');
}

export function fetchActivities(employeeId: string, limit = 20): Promise<CursorPage<Activity>> {
  return get<CursorPage<Activity>>(`/employees/${employeeId}/activities?limit=${limit}`);
}
