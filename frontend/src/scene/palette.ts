/**
 * 색의 출처를 한 곳에 모은다.
 *
 * 상태색의 단일 출처는 CSS(`tokens.css`)다. 3D 씬과 DOM 패널이 같은 초록/빨강을 써야
 * 하는데, 색을 두 곳에 적으면 반드시 갈라진다. CSS 변수를 읽어 three의 Color로 바꾼다 —
 * 그래서 토큰의 상태색만 hex로 두었다(three의 Color는 oklch를 파싱하지 못한다).
 *
 * 직무색은 다르다. 이건 **상태가 아니라 정체성**이라 서버 데이터가 아니라 표현 관심사다.
 * 상태색(변한다)과 직원 개성(변하지 않는다)을 분리해야 아바타가 상태를 바꿔도
 * "누구인지"가 유지된다. 그래서 여기 상수로 둔다.
 */

import { Color } from 'three';
import type { EmployeeStatus, Role } from '../api/types';

const STATUS_VARIABLE: Readonly<Record<EmployeeStatus, string>> = {
  WORKING: '--status-working',
  IDLE: '--status-idle',
  BLOCKED: '--status-blocked',
  ERROR: '--status-error',
  OFFLINE: '--status-offline',
};

const FALLBACK = '#94a3b8';

/** 직무별 몸통색. 파스텔 톤으로 눌러 상태색(선명)과 채도 충돌이 없게 한다. */
const ROLE_COLOR: Readonly<Record<Role, string>> = {
  COLLECTOR: '#7cc4e8',
  WRITER: '#f2b183',
  ANALYST: '#b3a1ec',
  TRADER: '#f0a3bf',
  ENGINEER: '#9cc5a1',
};

let cache: Map<EmployeeStatus, Color> | null = null;

/** getComputedStyle은 비싸다. 첫 호출에서 한 번만 읽는다. */
function load(): Map<EmployeeStatus, Color> {
  const computed = getComputedStyle(document.documentElement);
  const entries = Object.entries(STATUS_VARIABLE) as [EmployeeStatus, string][];
  return new Map(
    entries.map(([status, variable]) => {
      const raw = computed.getPropertyValue(variable).trim();
      return [status, new Color(raw === '' ? FALLBACK : raw)];
    }),
  );
}

export function statusColor(status: EmployeeStatus): Color {
  cache ??= load();
  return cache.get(status) ?? new Color(FALLBACK);
}

export function roleColor(role: Role): Color {
  return new Color(ROLE_COLOR[role] ?? FALLBACK);
}

/** OFFLINE은 반투명으로 둔다 — "자리에 없는 사람"이 색으로만 구분되면 눈에 걸린다. */
export function statusOpacity(status: EmployeeStatus): number {
  return status === 'OFFLINE' ? 0.3 : 1;
}
