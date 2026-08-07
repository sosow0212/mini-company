/**
 * 직원 상세 슬라이드오버 드로어 (Employee Detail Drawer).
 *
 * AI 직원이 사용하는 LLM 프로파일 모델 명시 및 수행 업무 결과 팝업 연동을 지원합니다.
 */

import { fetchActivities, fetchTasks, fireEmployee } from '../api/client';
import type { Activity, Employee, Task } from '../api/types';
import { ROLE_LABELS, TASK_STATUS_LABELS, WORKFLOWS } from '../api/types';
import { formatClockTime } from './format';

const RECENT_ACTIVITY_LIMIT = 15;

export interface EmployeePanelActions {
  readonly onAssign: (employee: Employee) => void;
  readonly onEdit: (employee: Employee) => void;
  readonly onFired: () => void;
  readonly onViewResult?: (task: Task, employeeName: string, llmProfile: string) => void;
}

export class EmployeePanel {
  private currentEmployeeId: string | null = null;
  private currentEmployee: Employee | null = null;
  private cachedTasks: readonly Task[] = [];
  private readonly backdrop: HTMLElement | null;

  constructor(
    private readonly host: HTMLElement,
    private readonly actions: EmployeePanelActions,
  ) {
    this.backdrop = document.getElementById('drawer-backdrop');

    this.backdrop?.addEventListener('click', () => {
      this.close();
    });

    window.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && this.currentEmployeeId !== null) {
        this.close();
      }
    });

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

      const viewBtn = target.closest<HTMLElement>('[data-view-result]');
      if (viewBtn !== null) {
        const taskId = viewBtn.dataset.viewResult;
        const task = this.cachedTasks.find((t) => t.id === taskId);
        if (task) {
          this.actions.onViewResult?.(task, employee.name, employee.llmProfile);
        }
      }
    });

    this.close();
  }

  private async fire(employee: Employee): Promise<void> {
    if (!window.confirm(`${employee.name} 직원 해고를 진행하시겠습니까?`)) {
      return;
    }
    const slot = this.host.querySelector('[data-panel-error]') as HTMLElement | null;
    try {
      await fireEmployee(employee.id);
      this.close();
      this.actions.onFired();
    } catch (error: unknown) {
      if (slot === null) return;
      slot.textContent = error instanceof Error ? error.message : '해고 요청을 처리하지 못했습니다.';
      slot.hidden = false;
    }
  }

  async open(employee: Employee): Promise<void> {
    this.currentEmployeeId = employee.id;
    this.currentEmployee = employee;
    this.host.hidden = false;

    requestAnimationFrame(() => {
      this.host.classList.add('is-open');
      this.backdrop?.classList.add('is-open');
    });

    this.host.innerHTML = this.markup(employee, null, null);

    try {
      const [activityPage, tasks] = await Promise.all([
        fetchActivities(employee.id, RECENT_ACTIVITY_LIMIT),
        fetchTasks(employee.id),
      ]);

      if (this.currentEmployeeId !== employee.id) return;
      this.cachedTasks = tasks;
      this.host.innerHTML = this.markup(employee, activityPage.items, tasks);
    } catch {
      if (this.currentEmployeeId !== employee.id) return;
      this.cachedTasks = [];
      this.host.innerHTML = this.markup(employee, [], []);
    }
  }

  close(): void {
    this.currentEmployeeId = null;
    this.currentEmployee = null;
    this.cachedTasks = [];
    this.host.classList.remove('is-open');
    this.backdrop?.classList.remove('is-open');
    setTimeout(() => {
      if (this.currentEmployeeId === null) {
        this.host.hidden = true;
        this.host.innerHTML = '';
      }
    }, 280);
  }

  get openedEmployeeId(): string | null {
    return this.currentEmployeeId;
  }

  private markup(
    employee: Employee,
    activities: readonly Activity[] | null,
    tasks: readonly Task[] | null,
  ): string {
    const hiredDate = new Date(employee.hiredAt).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

    return `
      <header class="drawer__header">
        <div class="drawer__profile-info">
          <h2 class="drawer__name">
            ${escape(employee.name)}
            <span class="drawer__role-badge">${ROLE_LABELS[employee.role]}</span>
          </h2>
          <p class="drawer__meta" style="display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.2rem;">
            <span style="
              padding: 0.1rem 0.4rem;
              border-radius: var(--radius-pill);
              background: rgba(6, 182, 212, 0.15);
              border: 1px solid rgba(6, 182, 212, 0.3);
              color: var(--cyan-accent);
              font-family: var(--font-mono);
              font-size: 0.68rem;
              font-weight: 600;
            ">🤖 ${escape(employee.llmProfile)}</span>
            <span>· 입사일: ${hiredDate}</span>
          </p>
          <div style="margin-top: 0.3rem;">
            <span class="status-chip" data-status="${employee.status}">${employee.status}</span>
          </div>
        </div>
        <button type="button" class="icon-button" data-close aria-label="닫기">✕</button>
      </header>

      <div class="drawer__actions">
        <button type="button" class="button button--primary" data-assign
                ${employee.currentTaskId === null ? '' : 'disabled'}>
          ⚡ 업무 지시
        </button>
        <button type="button" class="button button--ghost" data-edit>✏️ 수정</button>
        <button type="button" class="button button--danger" data-fire>🗑️ 해고</button>
      </div>

      ${
        employee.currentTaskId === null
          ? ''
          : `<p class="panel__note" style="margin: 0 1.5rem 0.5rem; color: #fbbf24;">⚠️ 현재 진행 중인 작업이 있어 새 작업 지시가 제한됩니다.</p>`
      }
      <p class="panel__error" data-panel-error role="alert" style="margin: 0 1.5rem;" hidden></p>

      <div class="drawer__body">
        <section class="drawer__section">
          <h3 class="drawer__section-title">📋 수행 업무 이력</h3>
          ${this.tasksMarkup(tasks)}
        </section>

        <section class="drawer__section">
          <h3 class="drawer__section-title">⏱️ 실시간 활동 로그</h3>
          ${this.activityMarkup(activities)}
        </section>
      </div>
    `;
  }

  private tasksMarkup(tasks: readonly Task[] | null): string {
    if (tasks === null) return `<p class="panel__empty">수행 업무를 불러오는 중…</p>`;
    if (tasks.length === 0) return `<p class="panel__empty">아직 부여된 업무가 없습니다.</p>`;

    return `<ol class="task-list">
      ${tasks
        .map((task) => {
          const what = WORKFLOWS.find((w) => w.kind === task.kind)?.label ?? task.kind;
          const when = task.startedAt ?? task.createdAt;
          const detail = task.status === 'SUCCEEDED' ? task.summary : (task.error ?? task.title);

          return `<li data-task-status="${task.status}">
            <div class="task-list__head">
              <span class="task-list__who">${escape(what)}</span>
              <span class="task-list__state">${TASK_STATUS_LABELS[task.status]}</span>
            </div>
            ${detail ? `<p class="task-list__detail">${escape(detail)}</p>` : ''}
            <div class="task-list__foot">
              <time>${formatClockTime(when)}</time>
              ${
                task.summary || task.error
                  ? `<button type="button" class="link-button" data-view-result="${task.id}">📄 결과 보기</button>`
                  : ''
              }
            </div>
          </li>`;
        })
        .join('')}
    </ol>`;
  }

  private activityMarkup(activities: readonly Activity[] | null): string {
    if (activities === null) return `<p class="panel__empty">활동 로그를 불러오는 중…</p>`;
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

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
