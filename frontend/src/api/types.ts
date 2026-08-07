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

export type TaskStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export interface Task {
  readonly id: string;
  readonly employeeId: string;
  readonly kind: string;
  /** 지시한 사람이 적은 한 줄. 워커는 이 값을 검색어·주제로 쓴다. */
  readonly title: string | null;
  readonly status: TaskStatus;
  readonly summary: string | null;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly error: string | null;
  readonly createdAt: string;
}

/**
 * 시킬 수 있는 일의 목록.
 *
 * 워커의 `src/workflows/__init__.py`가 실행 가능한 종류를 소유한다. 여기 목록에만 있고
 * 워커에 없으면 그 지시는 "알 수 없는 작업 종류"로 실패한다 — 양쪽을 함께 고쳐야 한다.
 */
export const WORKFLOWS = [
  {
    kind: 'collect_market_data',
    label: '자료 수집',
    hint: '외부 소스에서 문서를 가져와 지식 베이스에 적재합니다.',
    titlePlaceholder: '예: 주간 시장 자료',
  },
  {
    kind: 'analyze_knowledge',
    label: '자료 분석',
    hint: '적재된 자료를 검색해 핵심을 정리합니다. 제목이 검색어가 됩니다.',
    titlePlaceholder: '예: 반도체 수요',
  },
  {
    kind: 'write_report',
    label: '보고서 작성',
    hint: '근거를 찾아 보고서를 씁니다. 근거가 없으면 쓰지 않습니다.',
    titlePlaceholder: '예: 메모리 반도체 수요',
  },
] as const;

/** 반복 지시 — "매일 hour:minute에 이 직원에게 이 일을". */
export interface Schedule {
  readonly id: string;
  readonly employeeId: string;
  readonly kind: string;
  readonly title: string | null;
  readonly hour: number;
  readonly minute: number;
  readonly enabled: boolean;
  /** 마지막으로 작업을 만든 시각. null이면 아직 한 번도 안 돌았다. */
  readonly lastRunAt: string | null;
  readonly createdAt: string;
}

/** 지식 베이스에 적재된 문서 1건. 본문은 내려오지 않는다(길이만). */
export interface KnowledgeDocument {
  readonly id: string;
  readonly title: string;
  readonly sourceUrl: string | null;
  readonly sourceType: string;
  readonly contentType: string;
  readonly collectedBy: string;
  readonly taskId: string | null;
  readonly collectedAt: string;
  readonly chunkCount: number;
  readonly chunkingStrategy: string;
  readonly sectionCount: number;
  readonly indexedAt: string | null;
  readonly textLength: number;
  readonly metadata: {
    readonly title: string | null;
    readonly author: string | null;
    readonly description: string | null;
    readonly publishedAt: string | null;
    readonly siteName: string | null;
    readonly keywords: readonly string[];
  };
}

export const ROLE_LABELS: Readonly<Record<Role, string>> = {
  COLLECTOR: '수집가',
  ANALYST: '분석가',
  WRITER: '작가',
  TRADER: '트레이더',
  ENGINEER: '엔지니어',
};

export const TASK_STATUS_LABELS: Readonly<Record<TaskStatus, string>> = {
  QUEUED: '대기 중',
  RUNNING: '진행 중',
  SUCCEEDED: '완료',
  FAILED: '실패',
  CANCELLED: '취소됨',
};

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
