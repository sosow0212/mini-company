/**
 * 백엔드 응답 스키마와 1:1.
 *
 * 금액·카운트는 전부 `string`이다. 서버가 Decimal로 계산해 문자열로 내리고, 프론트는
 * 그걸 렌더링만 한다(ADR-006). `number`로 선언하면 JSON 파싱 단계에서 정밀도가 깎이고,
 * 산술 유혹도 생긴다 — 타입이 규칙을 지키게 둔다.
 */

export type EmployeeStatus = 'OFFLINE' | 'IDLE' | 'WORKING' | 'BLOCKED' | 'ERROR';
export type Role = 'COLLECTOR' | 'WRITER' | 'ANALYST' | 'TRADER' | 'ENGINEER';
export type ActivityLevel = 'INFO' | 'WARN' | 'ERROR';
export type LedgerCategory = 'REVENUE' | 'COST' | 'LLM_COST' | 'VIEWS' | 'SUBSCRIBERS';

export interface Desk {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

export interface Employee {
  readonly id: string;
  readonly name: string;
  readonly role: Role;
  readonly status: EmployeeStatus;
  readonly desk: Desk;
  readonly currentTaskId: string | null;
  readonly llmProfile: string;
  readonly hiredAt: string;
}

export interface LedgerSummary {
  readonly period: 'daily' | 'monthly' | 'all';
  readonly start: string | null;
  readonly end: string | null;
  readonly totals: Readonly<Record<LedgerCategory, string>>;
  readonly net: string;
}

export interface OfficeSnapshot {
  readonly employees: readonly Employee[];
  readonly ledger: LedgerSummary;
}

export interface Activity {
  readonly id: string;
  readonly employeeId: string;
  readonly taskId: string | null;
  readonly level: ActivityLevel;
  readonly message: string;
  readonly occurredAt: string;
}

export interface CursorPage<T> {
  readonly items: readonly T[];
  readonly nextCursor: string | null;
}

/** 서버 → 클라이언트 이벤트. `type`이 판별자라 switch 하나로 분기한다. */
export type OfficeEvent =
  | {
      readonly type: 'employee.status_changed';
      readonly data: {
        readonly employeeId: string;
        readonly status: EmployeeStatus;
        readonly currentTaskId: string | null;
      };
    }
  | {
      readonly type: 'activity.created';
      readonly data: {
        readonly employeeId: string;
        readonly taskId: string | null;
        readonly level: ActivityLevel;
        readonly message: string;
        readonly occurredAt: string;
      };
    }
  | {
      readonly type: 'ledger.summary_updated';
      readonly data: LedgerSummary;
    };
