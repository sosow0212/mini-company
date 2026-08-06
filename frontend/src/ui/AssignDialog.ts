/**
 * 작업 지시 폼.
 *
 * 종류(kind)와 한 줄 제목을 받는다. 제목은 장식이 아니다 — 분석·보고서 워크플로우는
 * 이 값을 **검색어/주제로 쓴다.** 그래서 종류를 고르면 안내 문구와 예시가 바뀐다.
 *
 * 지시는 QUEUED로 들어간다. 워커가 집어가야 RUNNING이 되므로, 에이전트가 떠 있지
 * 않으면 대기 상태로 남는다 — 그 사실이 화면에 그대로 보이는 편이 낫다.
 */

import { assignTask } from '../api/client';
import type { Employee, Task } from '../api/types';
import { WORKFLOWS } from '../api/types';
import { FormDialog } from './FormDialog';

export class AssignDialog extends FormDialog<Task> {
  private employeeId = '';

  constructor() {
    super('일 시키기', '지시하기');
    this.body.innerHTML = `
      <p class="dialog__lead" data-target></p>
      <label class="field">
        <span class="field__label">무슨 일</span>
        <select name="kind">
          ${WORKFLOWS.map(
            (workflow) => `<option value="${workflow.kind}">${workflow.label}</option>`,
          ).join('')}
        </select>
      </label>
      <label class="field">
        <span class="field__label">지시 내용</span>
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
      `${employee.name}에게 일을 맡깁니다.`;
    (this.body.querySelector('[name="title"]') as HTMLInputElement).value = '';
    this.open();
  }

  private syncHint(): void {
    const kind = (this.body.querySelector('[name="kind"]') as HTMLSelectElement).value;
    const workflow = WORKFLOWS.find((item) => item.kind === kind);
    if (workflow === undefined) return;
    (this.body.querySelector('[data-hint]') as HTMLElement).textContent = workflow.hint;
    (this.body.querySelector('[name="title"]') as HTMLInputElement).placeholder =
      workflow.titlePlaceholder;
  }

  protected async submit(): Promise<Task> {
    const kind = (this.body.querySelector('[name="kind"]') as HTMLSelectElement).value;
    const title = (this.body.querySelector('[name="title"]') as HTMLInputElement).value.trim();
    return assignTask(this.employeeId, kind, title);
  }
}
