/**
 * 작업 목록 (Task Panel).
 *
 * 현재 진행 중이거나 최근 시킨 일들의 목록과 결과를 보여주며,
 * 결과 클릭 시 상세 보고서 팝업을 열 수 있습니다.
 */

import { cancelTask, fetchTasks } from '../api/client';
import type { Employee, Task } from '../api/types';
import { TASK_STATUS_LABELS, WORKFLOWS } from '../api/types';
import { formatClockTime } from './format';

const REFRESH_MS = 3_000;
const VISIBLE_LIMIT = 10;

export class TaskPanel {
  private tasks: readonly Task[] = [];
  private employeeNames = new Map<string, string>();
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
  }

  setOnViewResult(handler: (task: Task, employeeName: string) => void): void {
    this.onViewResultHandler = handler;
  }

  setEmployees(employees: readonly Employee[]): void {
    this.employeeNames = new Map(employees.map((employee) => [employee.id, employee.name]));
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
    const detail = task.status === 'SUCCEEDED' ? task.summary : (task.error ?? task.title);

    return `<li data-task-status="${task.status}">
      <div class="task-list__head">
        <span class="task-list__who">${escape(who)}</span>
        <span class="task-list__what">${escape(what)}</span>
        <span class="task-list__state">${TASK_STATUS_LABELS[task.status]}</span>
      </div>
      ${detail ? `<p class="task-list__detail">${escape(detail)}</p>` : ''}
      <div class="task-list__foot">
        <time>${formatClockTime(when)}</time>
        <div>
          ${
            task.summary || task.error
              ? `<button type="button" class="link-button" data-view-result="${task.id}" style="margin-right: 0.5rem;">📄 결과 보기</button>`
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
}

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
