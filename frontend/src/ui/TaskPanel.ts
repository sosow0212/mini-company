/**
 * 작업 목록 — 시킨 일이 지금 어디까지 갔는지.
 *
 * 이 패널이 답하는 질문은 하나다: **"내가 시킨 게 돌고 있나?"**
 * QUEUED가 계속 쌓여 있으면 에이전트(`python -m src.agent`)가 떠 있지 않다는 뜻이고,
 * 그 사실이 화면에 드러나야 한다 — 안 그러면 "시켰는데 아무 일도 안 일어난다"로만 보인다.
 *
 * 목록은 WS 이벤트가 아니라 폴링으로 갱신한다. 작업 상태 전이는 전용 이벤트가 없고
 * (직원 상태 변경 이벤트로 간접 추론해야 한다), 몇 초 늦어도 되는 정보다.
 */

import { cancelTask, fetchTasks } from '../api/client';
import type { Employee, Task } from '../api/types';
import { TASK_STATUS_LABELS, WORKFLOWS } from '../api/types';
import { formatClockTime } from './format';

const REFRESH_MS = 3_000;
const VISIBLE_LIMIT = 8;

export class TaskPanel {
  private tasks: readonly Task[] = [];
  private employeeNames = new Map<string, string>();

  constructor(private readonly host: HTMLElement) {
    this.host.addEventListener('click', (event) => {
      const button = (event.target as HTMLElement).closest<HTMLElement>('[data-cancel-task]');
      if (button === null) return;
      void this.cancel(button.dataset.cancelTask as string);
    });
    this.render();
    window.setInterval(() => void this.refresh(), REFRESH_MS);
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
      // 폴링 실패는 조용히 넘긴다. 다음 주기에 다시 시도하고, 연결 배지가 이미
      // 끊김을 알린다 — 여기서 또 에러를 띄우면 화면이 경고로 덮인다.
    }
  }

  private async cancel(taskId: string): Promise<void> {
    try {
      await cancelTask(taskId);
    } catch {
      // 이미 워커가 집어간 경우다(409). 새로고침하면 RUNNING으로 보인다.
    }
    await this.refresh();
  }

  private render(): void {
    const pending = this.tasks.filter(
      (task) => task.status === 'QUEUED' || task.status === 'RUNNING',
    ).length;

    this.host.innerHTML = `
      <header class="panel__head">
        <h2 class="panel__title">작업</h2>
        ${pending > 0 ? `<span class="panel__count">진행 ${String(pending)}건</span>` : ''}
      </header>
      ${this.listMarkup()}
    `;
  }

  private listMarkup(): string {
    if (this.tasks.length === 0) {
      return `<p class="panel__empty">아직 시킨 일이 없습니다.<br />직원을 클릭해 일을 맡겨보세요.</p>`;
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
    // 완료된 작업은 결과를, 진행 중인 작업은 지시 내용을 보여준다.
    const detail = task.status === 'SUCCEEDED' ? task.summary : (task.error ?? task.title);
    return `<li data-task-status="${task.status}">
      <div class="task-list__head">
        <span class="task-list__who">${escape(who)}</span>
        <span class="task-list__what">${escape(what)}</span>
        <span class="task-list__state">${TASK_STATUS_LABELS[task.status]}</span>
      </div>
      ${detail === null || detail === '' ? '' : `<p class="task-list__detail">${escape(detail)}</p>`}
      <div class="task-list__foot">
        <time>${formatClockTime(when)}</time>
        ${
          task.status === 'QUEUED'
            ? `<button type="button" class="link-button" data-cancel-task="${task.id}">취소</button>`
            : ''
        }
      </div>
    </li>`;
  }
}

/** 서버 문자열을 innerHTML에 넣기 전에 이스케이프한다. 요약문은 LLM 출력이다. */
function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
