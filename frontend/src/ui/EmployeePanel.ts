/**
 * 직원 상세 — 아바타를 클릭하면 열린다.
 *
 * 활동 로그는 클릭 시점에 서버에서 다시 받는다(커서 페이지네이션 1페이지). store의
 * 최근 3건은 말풍선용 캐시이고, 이력의 주인은 서버다.
 */

import { fetchActivities } from '../api/client';
import type { Activity, Employee } from '../api/types';
import { formatClockTime } from './format';

export class EmployeePanel {
  private currentEmployeeId: string | null = null;

  constructor(private readonly host: HTMLElement) {
    this.host.addEventListener('click', (event) => {
      if ((event.target as HTMLElement).closest('[data-close]') !== null) this.close();
    });
    this.close();
  }

  async open(employee: Employee): Promise<void> {
    this.currentEmployeeId = employee.id;
    this.host.hidden = false;
    this.host.innerHTML = this.markup(employee, null);

    try {
      const page = await fetchActivities(employee.id);
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
          <p class="panel__sub">${employee.role.toLowerCase()} · ${escape(employee.llmProfile)}</p>
        </div>
        <button type="button" class="icon-button" data-close aria-label="닫기">✕</button>
      </header>
      <p class="status-chip" data-status="${employee.status}">${employee.status}</p>
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
