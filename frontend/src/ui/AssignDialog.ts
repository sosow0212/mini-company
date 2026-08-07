/**
 * 작업 지시 폼 (Assign Task Dialog).
 *
 * 직원의 이름과 담당 AI LLM 모델 정보를 명시하며,
 * 선택한 워크플로우에 맞는 안내문구와 예시를 제공합니다.
 */

import { assignTask } from '../api/client';
import type { Employee, Task } from '../api/types';
import { WORKFLOWS } from '../api/types';
import { FormDialog } from './FormDialog';

export class AssignDialog extends FormDialog<Task> {
  private employeeId = '';

  constructor() {
    super('업무 지시 (Task Assignment)', '지시하기');
    this.body.innerHTML = `
      <div class="drawer__card" style="background: rgba(99, 102, 241, 0.1); border-color: rgba(99, 102, 241, 0.3);">
        <p class="dialog__lead" data-target style="margin: 0; font-weight: 600; color: var(--text);"></p>
        <p data-model-info style="margin: 0.25rem 0 0; font-size: var(--text-label); color: var(--accent-light); font-family: var(--font-mono);"></p>
      </div>
      <label class="field">
        <span class="field__label">무슨 일 (워크플로우)</span>
        <select name="kind">
          ${WORKFLOWS.map(
            (workflow) => `<option value="${workflow.kind}">${workflow.label}</option>`,
          ).join('')}
        </select>
      </label>
      <label class="field">
        <span class="field__label">지시 주제 / 제목</span>
        <input name="title" type="text" maxlength="120" autocomplete="off" />
      </label>
      <p class="field__hint" data-hint></p>
    `;

    const kindSelect = this.body.querySelector('[name="kind"]') as HTMLSelectElement;
    kindSelect.addEventListener('change', () => {
      this.syncHint();
    });
    this.syncHint();
  }

  show(employee: Employee): void {
    this.employeeId = employee.id;
    (this.body.querySelector('[data-target]') as HTMLElement).textContent =
      `⚡ ${employee.name} 직원에게 새로운 업무를 시킵니다.`;
    (this.body.querySelector('[data-model-info]') as HTMLElement).textContent =
      `🤖 탑재 LLM 프로파일: ${employee.llmProfile}`;
    (this.body.querySelector('[name="title"]') as HTMLInputElement).value = '';
    this.open();
  }

  private syncHint(): void {
    const kind = (this.body.querySelector('[name="kind"]') as HTMLSelectElement).value;
    const workflow = WORKFLOWS.find((item) => item.kind === kind);
    if (workflow === undefined) return;
    (this.body.querySelector('[data-hint]') as HTMLElement).textContent = `💡 ${workflow.hint}`;
    (this.body.querySelector('[name="title"]') as HTMLInputElement).placeholder =
      workflow.titlePlaceholder;
  }

  protected async submit(): Promise<Task> {
    const kind = (this.body.querySelector('[name="kind"]') as HTMLSelectElement).value;
    const title = (this.body.querySelector('[name="title"]') as HTMLInputElement).value.trim();
    return assignTask(this.employeeId, kind, title);
  }
}
