/**
 * 작업 결과 상세 모달 (Task Result Dialog).
 *
 * AI 직원이 LLM 모델을 사용하여 수행 완료한 분석 보고서, 수집 결과 요약,
 * 또는 발생한 에러 메시지 전문을 가독성 높은 전용 뷰어로 보여줍니다.
 */

import type { Task } from '../api/types';
import { TASK_STATUS_LABELS, WORKFLOWS } from '../api/types';
import { formatClockTime } from './format';

export class TaskResultDialog {
  private readonly dialog: HTMLDialogElement;
  private readonly titleEl: HTMLElement;
  private readonly metaEl: HTMLElement;
  private readonly contentEl: HTMLElement;

  constructor() {
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'dialog';
    this.dialog.style.width = 'min(44rem, calc(100vw - 2rem))';
    this.dialog.innerHTML = `
      <div class="dialog__form">
        <header class="dialog__head">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span style="font-size: 1.2rem;">📄</span>
            <h2 class="dialog__title" data-title>작업 수행 결과 보고서</h2>
          </div>
          <button type="button" class="icon-button" data-close aria-label="닫기">✕</button>
        </header>

        <div class="dialog__body">
          <div class="drawer__card" data-meta style="background: rgba(0, 0, 0, 0.25); border: 1px solid var(--line);"></div>

          <div class="field">
            <span class="field__label" style="color: var(--accent-light);">🤖 LLM 생성 결과 / 요약 리포트</span>
            <div data-content style="
              padding: 1rem;
              background: rgba(0, 0, 0, 0.4);
              border: 1px solid var(--line-strong);
              border-radius: var(--radius-small);
              font-family: var(--font-ui);
              font-size: var(--text-body);
              line-height: 1.65;
              color: var(--text);
              max-height: 22rem;
              overflow-y: auto;
              white-space: pre-wrap;
              word-break: break-word;
            "></div>
          </div>
        </div>

        <footer class="dialog__foot">
          <button type="button" class="button button--primary" data-close>확인</button>
        </footer>
      </div>
    `;
    document.body.append(this.dialog);

    this.titleEl = this.dialog.querySelector('[data-title]') as HTMLElement;
    this.metaEl = this.dialog.querySelector('[data-meta]') as HTMLElement;
    this.contentEl = this.dialog.querySelector('[data-content]') as HTMLElement;

    for (const button of this.dialog.querySelectorAll('[data-close]')) {
      button.addEventListener('click', () => this.dialog.close());
    }
  }

  show(task: Task, employeeName: string, llmProfile?: string): void {
    const workflow = WORKFLOWS.find((w) => w.kind === task.kind);
    const kindLabel = workflow?.label ?? task.kind;
    const when = formatClockTime(task.finishedAt ?? task.startedAt ?? task.createdAt);
    const modelText = llmProfile ? ` · 모델: ${llmProfile}` : '';

    this.titleEl.textContent = `${kindLabel} — ${task.title ?? '기본 임무'}`;

    this.metaEl.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
        <div>
          <span style="font-weight: 700; color: var(--text);">${escape(employeeName)}</span>
          <span style="color: var(--text-dim); font-size: var(--text-label);">${modelText}</span>
        </div>
        <div>
          <span class="task-list__state" style="font-size: var(--text-label);">${TASK_STATUS_LABELS[task.status]}</span>
          <span style="color: var(--text-faint); font-size: var(--text-tag); margin-left: 0.5rem;">${when}</span>
        </div>
      </div>
    `;

    const mainText =
      task.status === 'SUCCEEDED'
        ? task.summary ?? '수행 결과 요약이 없습니다.'
        : task.error ?? task.summary ?? '오류 상세 정보가 없습니다.';

    this.contentEl.style.color = task.status === 'FAILED' ? '#f87171' : 'var(--text)';
    this.contentEl.textContent = mainText;

    this.dialog.showModal();
  }
}

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
