/**
 * fetch 래퍼.
 *
 * 개발 서버와 nginx가 `/api`를 백엔드로 프록시하므로 브라우저 기준 동일 출처다.
 * 그래서 절대 URL도, CORS도 필요 없다.
 */

import type { Activity, CursorPage, Employee, OfficeSnapshot, Role, Task } from './types';

const API = '/api/v1';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    /**
     * 서버가 준 한국어 문장. 화면에 그대로 띄운다.
     *
     * 프론트에 code→문구 표를 따로 두지 않는 이유: 같은 문구가 두 곳에 생기고,
     * 백엔드에서 메시지를 고쳐도 화면은 옛 문구를 계속 보여준다.
     */
    readonly detail: string,
  ) {
    super(detail || `API ${status} (${code})`);
    this.name = 'ApiError';
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'unknown';
  let detail = '';
  try {
    const body: unknown = await response.json();
    if (body !== null && typeof body === 'object') {
      const record = body as Record<string, unknown>;
      if ('code' in record) code = String(record.code);
      if (typeof record.message === 'string') detail = record.message;
      // FastAPI 검증 실패는 형태가 다르다(detail 배열). 그대로 노출하면 읽을 수 없다.
      if (detail === '' && response.status === 422) detail = '입력값을 확인해 주세요.';
    }
  } catch {
    // 본문이 JSON이 아니면 상태코드만으로 충분하다.
  }
  return new ApiError(response.status, code, detail);
}

/** 진입 시 1회, WS 재연결 직후 1회. 이 두 시점 외에는 부르지 않는다. */
export function fetchSnapshot(): Promise<OfficeSnapshot> {
  return get<OfficeSnapshot>('/office/snapshot');
}

export function fetchActivities(employeeId: string, limit = 20): Promise<CursorPage<Activity>> {
  return get<CursorPage<Activity>>(`/employees/${employeeId}/activities?limit=${limit}`);
}

/**
 * 상태를 바꾸는 요청.
 *
 * 204(본문 없음)를 별도로 다룬다 — 해고가 그렇다. `response.json()`을 무조건 부르면
 * "Unexpected end of JSON input"으로 실패한다.
 */
async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  // exactOptionalPropertyTypes를 켜둔 탓에 `body: undefined`를 그대로 넘길 수 없다.
  // 본문이 없는 요청(DELETE·취소)에서는 키 자체를 빼야 한다.
  const init: RequestInit = {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function hireEmployee(name: string, role: Role): Promise<Employee> {
  // 책상 좌표와 LLM 프로파일은 보내지 않는다. 서버가 정한다.
  return send<Employee>('POST', '/employees', { name, role });
}

export function updateEmployee(
  id: string,
  changes: { name?: string; role?: Role },
): Promise<Employee> {
  return send<Employee>('PATCH', `/employees/${id}`, changes);
}

export function fireEmployee(id: string): Promise<void> {
  return send<void>('DELETE', `/employees/${id}`);
}

export function fetchTasks(employeeId?: string): Promise<readonly Task[]> {
  const query = employeeId === undefined ? '' : `?employee_id=${employeeId}`;
  return get<readonly Task[]>(`/tasks${query}`);
}

export function assignTask(employeeId: string, kind: string, title: string): Promise<Task> {
  return send<Task>('POST', '/tasks', { employeeId, kind, title: title || null });
}

export function cancelTask(taskId: string): Promise<Task> {
  return send<Task>('POST', `/tasks/${taskId}/cancel`);
}
