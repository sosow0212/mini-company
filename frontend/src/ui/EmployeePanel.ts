/**
 * 직원 상세 — 아바타를 클릭하면 열린다.
 *
 * 활동 로그는 클릭 시점에 서버에서 다시 받는다(커서 페이지네이션 1페이지). store의
 * 최근 3건은 말풍선용 캐시이고, 이력의 주인은 서버다.
 */

import { fetchActivities, fireEmployee } from '../api/client';
import type { Activity, Employee } from '../api/types';
import { ROLE_LABELS } from '../api/types';
import { formatClockTime } from './format';

/** 상세 패널이 한 번에 보여줄 활동 수. */
const _RECENT_ACTIVITY_LIMIT = 8;

export interface EmployeePanelActions {
  readonly onAssign: (employee: Employee) => void;
  readonly onEdit: (employee: Employee) => void;
  /** 해고 성공 후. 목록을 다시 받아야 아바타가 사라진다. */
  readonly onFired: () => void;
}

export class EmployeePanel {
  private currentEmployeeId: string | null = null;
  private currentEmployee: Employee | null = null;

  constructor(
    private readonly host: HTMLElement,
    private readonly actions: EmployeePanelActions,
  ) {
    this.host.addEventListener('click', (event) => {
      const target = event.target as HTMLElement;
      if (target.closest('[data-close]') !== null) {
        this.close();
        return;
      }
      const employee = this.currentEmployee;
      if (employee === null) return;

      if (target.closest('[data-assign]') !== null) this.actions.onAssign(employee);
      if (target.closest('[data-edit]') !== null) this.actions.onEdit(employee);
      if (target.closest('[data-fire]') !== null) void this.fire(employee);
    });
    this.close();
  }

  private async fire(employee: Employee): Promise<void> {
    // 되돌릴 수 없는 동작이라 확인을 받는다. 활동·원장 기록은 남지만 직원은 사라진다.
    if (!window.confirm(`${employee.name}을(를) 해고할까요?`)) return;
    const slot = this.host.querySelector('[data-panel-error]') as HTMLElement | null;
    try {
      await fireEmployee(employee.id);
      this.close();
      this.actions.onFired();
    } catch (error: unknown) {
      // 작업 중이면 409다. 서버 문장을 그대로 보여준다.
      if (slot === null) return;
      slot.textContent = error instanceof Error ? error.message : '해고하지 못했습니다.';
      slot.hidden = false;
    }
  }

  async open(employee: Employee): Promise<void> {
    this.currentEmployeeId = employee.id;
    this.currentEmployee = employee;
    this.host.hidden = false;
    // 레일이 아래로 스크롤된 상태일 수 있다. 열었는데 화면 밖이면 안 열린 것과 같다.
    this.host.scrollIntoView({ block: 'nearest' });
    this.host.innerHTML = this.markup(employee, null);

    try {
      // 패널은 '지금 뭘 하고 있나'를 보여주는 곳이다. 전체 이력이 필요하면
      // 서버에 커서 페이지네이션이 있다.
      const page = await fetchActivities(employee.id, _RECENT_ACTIVITY_LIMIT);
      // 열려 있는 직원이 바뀌었으면 늦게 도착한 응답을 버린다.
      if (this.currentEmployeeId !== employee.id) return;
      this.host.innerHTML = this.markup(employee, page.items);
    } catch {
      if (this.currentEmployeeId !== employee.id) return;
      this.host.innerHTML = this.markup(employee, []);
    }
  }

  close(): void {
    this.currentEmployeeId = null;
    this.currentEmployee = null;
    this.host.hidden = true;
    this.host.innerHTML = '';
  }

  get openedEmployeeId(): string | null {
    return this.currentEmployeeId;
  }

  private markup(employee: Employee, activities: readonly Activity[] | null): string {
    return `
      <header class="panel__head">
        <div>
          <h2 class="panel__title">${escape(employee.name)}</h2>
          <p class="panel__sub">${ROLE_LABELS[employee.role]} · ${escape(employee.llmProfile)}</p>
        </div>
        <button type="button" class="icon-button" data-close aria-label="닫기">✕</button>
      </header>
      <p class="status-chip" data-status="${employee.status}">${employee.status}</p>
      <div class="panel__actions">
        <button type="button" class="button button--primary" data-assign
                ${employee.currentTaskId === null ? '' : 'disabled'}>
          일 시키기
        </button>
        <button type="button" class="button button--ghost" data-edit>수정</button>
        <button type="button" class="button button--danger" data-fire>해고</button>
      </div>
      ${
        employee.currentTaskId === null
          ? ''
          : `<p class="panel__note">지금 다른 일을 하고 있어 새 지시를 받을 수 없습니다.</p>`
      }
      <p class="panel__error" data-panel-error role="alert" hidden></p>
      <h3 class="panel__section">활동 로그</h3>
      ${this.activityMarkup(activities)}
    `;
  }

  private activityMarkup(activities: readonly Activity[] | null): string {
    if (activities === null) return `<p class="panel__empty">불러오는 중…</p>`;
    if (activities.length === 0) return `<p class="panel__empty">기록된 활동이 없습니다.</p>`;
    return `<ol class="activity-log">
      ${activities
        .map(
          (activity) => `<li data-level="${activity.level}">
            <time>${formatClockTime(activity.occurredAt)}</time>
            <span>${escape(activity.message)}</span>
          </li>`,
        )
        .join('')}
    </ol>`;
  }
}

/** 서버 문자열을 innerHTML에 넣기 전에 이스케이프한다. 활동 메시지는 LLM 출력일 수 있다. */
function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
