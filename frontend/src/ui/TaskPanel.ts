/**
 * 작업 목록 (Task Panel).
 *
 * 현재 진행 중이거나 최근 시킨 일들의 목록과 결과를 보여주며,
 * 결과 클릭 시 상세 보고서 팝업을 열 수 있습니다.
 */

import { cancelTask, fetchTasks } from '../api/client';
import type { Activity, Employee, Task } from '../api/types';
import { TASK_STATUS_LABELS, WORKFLOWS } from '../api/types';
import { formatClockTime } from './format';

const REFRESH_MS = 3_000;
const VISIBLE_LIMIT = 10;
/** 경과 시간을 다시 그리는 주기. 초 단위로 보여주므로 1초면 충분하다. */
const TICK_MS = 1_000;

/** 진행 중인 작업이 "지금 무슨 단계인가"의 원천. store의 최근 활동을 그대로 쓴다. */
export interface EmployeeProgress {
  readonly employee: Employee;
  readonly recentActivities: readonly Activity[];
}

export class TaskPanel {
  private tasks: readonly Task[] = [];
  private employeeNames = new Map<string, string>();
  private progress = new Map<string, EmployeeProgress>();
  private onViewResultHandler: ((task: Task, employeeName: string) => void) | null = null;

  constructor(private readonly host: HTMLElement) {
    this.host.addEventListener('click', (event) => {
      const target = event.target as HTMLElement;

      const cancelBtn = target.closest<HTMLElement>('[data-cancel-task]');
      if (cancelBtn !== null) {
        void this.cancel(cancelBtn.dataset.cancelTask as string);
        return;
      }

      const viewBtn = target.closest<HTMLElement>('[data-view-result]');
      if (viewBtn !== null) {
        const taskId = viewBtn.dataset.viewResult;
        const task = this.tasks.find((t) => t.id === taskId);
        if (task) {
          const who = this.employeeNames.get(task.employeeId) ?? '(퇴사)';
          this.onViewResultHandler?.(task, who);
        }
      }
    });
    this.render();
    window.setInterval(() => void this.refresh(), REFRESH_MS);
    // 경과 시간만 흐르는 동안에도 숫자가 멈춰 보이지 않게 다시 그린다.
    window.setInterval(() => {
      if (this.tasks.some((task) => task.status === 'RUNNING')) this.render();
    }, TICK_MS);
  }

  setOnViewResult(handler: (task: Task, employeeName: string) => void): void {
    this.onViewResultHandler = handler;
  }

  setEmployees(employees: readonly Employee[]): void {
    this.employeeNames = new Map(employees.map((employee) => [employee.id, employee.name]));
    this.render();
  }

  /**
   * 진행 중인 작업의 "현재 단계"를 공급한다.
   *
   * 활동은 WS로 실시간 도착하므로(`activity.created`) 3초 폴링보다 먼저 갱신된다.
   * 이게 없으면 "진행 중"이라는 글자만 몇 분간 떠 있고, 멈춘 건지 일하는 건지 알 수 없다.
   */
  setProgress(views: readonly EmployeeProgress[]): void {
    this.progress = new Map(views.map((view) => [view.employee.id, view]));
    this.render();
  }

  async refresh(): Promise<void> {
    try {
      this.tasks = await fetchTasks();
      this.render();
    } catch {
      // 폴링 실패 시 스킵
    }
  }

  private async cancel(taskId: string): Promise<void> {
    try {
      await cancelTask(taskId);
    } catch {
      // 이미 실행 중이면 스킵
    }
    await this.refresh();
  }

  private render(): void {
    const pending = this.tasks.filter(
      (task) => task.status === 'QUEUED' || task.status === 'RUNNING',
    ).length;

    this.host.innerHTML = `
      <header class="panel__head">
        <h2 class="panel__title">⚡ 작업 현황</h2>
        ${pending > 0 ? `<span class="panel__count">진행 중 ${String(pending)}건</span>` : ''}
      </header>
      ${this.listMarkup()}
    `;
  }

  private listMarkup(): string {
    if (this.tasks.length === 0) {
      return `<p class="panel__empty">아직 부여된 작업이 없습니다.<br />직원을 클릭해 새로운 일을 시켜보세요.</p>`;
    }
    return `<ol class="task-list">
      ${this.tasks
        .slice(0, VISIBLE_LIMIT)
        .map((task) => this.itemMarkup(task))
        .join('')}
    </ol>`;
  }

  private itemMarkup(task: Task): string {
    const who = this.employeeNames.get(task.employeeId) ?? '(퇴사)';
    const what = WORKFLOWS.find((workflow) => workflow.kind === task.kind)?.label ?? task.kind;
    const when = task.startedAt ?? task.createdAt;
    const running = task.status === 'RUNNING';

    return `<li data-task-status="${task.status}">
      <div class="task-list__head">
        <span class="task-list__who">${escape(who)}</span>
        <span class="task-list__what">${escape(what)}</span>
        <span class="task-list__state">
          ${running ? '<span class="pulse" aria-hidden="true"></span>' : ''}
          ${TASK_STATUS_LABELS[task.status]}
        </span>
      </div>
      ${this.bodyMarkup(task)}
      <div class="task-list__foot">
        <time>${formatClockTime(when)}</time>
        <div>
          ${
            running && task.startedAt !== null
              ? `<span class="task-list__elapsed">${formatElapsed(task.startedAt)}</span>`
              : ''
          }
          ${
            task.status === 'QUEUED'
              ? `<span class="task-list__hint">에이전트를 기다리는 중</span>`
              : ''
          }
          ${
            task.summary || task.error
              ? `<button type="button" class="link-button" data-view-result="${task.id}">📄 결과 보기</button>`
              : ''
          }
          ${
            task.status === 'QUEUED'
              ? `<button type="button" class="link-button" data-cancel-task="${task.id}">취소</button>`
              : ''
          }
        </div>
      </div>
    </li>`;
  }

  /** 진행 중이면 지금 무슨 단계인지, 끝났으면 결과를 보여준다. */
  private bodyMarkup(task: Task): string {
    if (task.status === 'RUNNING') {
      const step = this.progress.get(task.employeeId)?.recentActivities.at(0);
      // 활동이 아직 없으면 하네스가 막 붙은 참이다.
      return `<p class="task-list__step">${escape(step?.message ?? '작업을 시작하는 중…')}</p>`;
    }
    const detail = task.status === 'SUCCEEDED' ? task.summary : (task.error ?? task.title);
    return detail ? `<p class="task-list__detail">${escape(detail)}</p>` : '';
  }
}

/** 시작 후 흐른 시간. 분을 넘기면 초는 버린다 — 그 정밀도가 의미를 갖지 않는다. */
function formatElapsed(startedAt: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${String(seconds)}초째`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${String(minutes)}분째`;
  return `${String(Math.floor(minutes / 60))}시간 ${String(minutes % 60)}분째`;
}

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
