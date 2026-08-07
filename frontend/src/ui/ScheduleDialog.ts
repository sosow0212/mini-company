/**
 * 반복 지시 등록.
 *
 * 시각은 `<input type="time">`으로 받는다 — 브라우저가 지역 형식(오전/오후)과 키보드
 * 입력을 알아서 처리한다. 직접 만든 선택기는 그 둘을 반드시 놓친다.
 *
 * cron 문자열을 받지 않는 이유는 `schedules/schemas.py`에 적어뒀다: 잘못 만든 표현식은
 * 저장은 되고 실행만 안 된다.
 */

import { createSchedule } from '../api/client';
import type { Employee, Schedule } from '../api/types';
import { WORKFLOWS } from '../api/types';
import { FormDialog } from './FormDialog';

export class ScheduleDialog extends FormDialog<Schedule> {
  private employees: readonly Employee[] = [];

  constructor() {
    super('반복 지시 추가', '등록');
    this.body.innerHTML = `
      <p class="dialog__lead">정해진 시각이 되면 에이전트가 알아서 실행합니다.</p>
      <label class="field">
        <span class="field__label">누가</span>
        <select name="employee"></select>
      </label>
      <label class="field">
        <span class="field__label">무슨 일</span>
        <select name="kind">
          ${WORKFLOWS.map(
            (workflow) => `<option value="${workflow.kind}">${workflow.label}</option>`,
          ).join('')}
        </select>
      </label>
      <label class="field">
        <span class="field__label">매일 몇 시</span>
        <input name="time" type="time" value="09:00" required />
      </label>
      <label class="field">
        <span class="field__label">지시 내용</span>
        <input name="title" type="text" maxlength="120" autocomplete="off" />
      </label>
      <p class="field__hint" data-hint></p>
    `;

    this.body.querySelector('[name="kind"]')?.addEventListener('change', () => {
      this.syncHint();
    });
    this.syncHint();
  }

  show(employees: readonly Employee[]): void {
    this.employees = employees;
    const select = this.body.querySelector('[name="employee"]') as HTMLSelectElement;
    select.innerHTML = employees
      .map((employee) => `<option value="${employee.id}">${escapeAttr(employee.name)}</option>`)
      .join('');
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

  protected async submit(): Promise<Schedule> {
    const employeeId = (this.body.querySelector('[name="employee"]') as HTMLSelectElement).value;
    const kind = (this.body.querySelector('[name="kind"]') as HTMLSelectElement).value;
    const title = (this.body.querySelector('[name="title"]') as HTMLInputElement).value.trim();
    const time = (this.body.querySelector('[name="time"]') as HTMLInputElement).value;

    if (this.employees.length === 0) throw new Error('먼저 직원을 채용하세요.');
    // `<input type="time">`은 HH:MM을 주지만 타입 시스템은 그걸 모른다.
    // 비어 있는 채로 제출되는 경우(브라우저 검증 우회)까지 여기서 막는다.
    const [hourText, minuteText] = time.split(':');
    if (hourText === undefined || minuteText === undefined) {
      throw new Error('시각을 선택하세요.');
    }
    return createSchedule({
      employeeId,
      kind,
      hour: Number(hourText),
      minute: Number(minuteText),
      title,
    });
  }
}

/** 속성값에 들어가므로 따옴표까지 막아야 한다. */
function escapeAttr(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML.replaceAll('"', '&quot;');
}
