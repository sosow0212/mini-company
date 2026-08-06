/**
 * 직원 정보 수정.
 *
 * 상태(WORKING/IDLE)를 바꾸는 입력란이 없다. 그건 작업 실행이 만드는 결과이지 사람이
 * 쓰는 값이 아니다 — 손으로 IDLE로 돌리면 실제로 돌고 있는 워커와 화면이 어긋난다.
 */

import { updateEmployee } from '../api/client';
import type { Employee, Role } from '../api/types';
import { ROLE_LABELS } from '../api/types';
import { FormDialog } from './FormDialog';

export class EditDialog extends FormDialog<Employee> {
  private employeeId = '';

  constructor() {
    super('직원 정보 수정', '저장');
    this.body.innerHTML = `
      <label class="field">
        <span class="field__label">이름</span>
        <input name="name" type="text" maxlength="30" required autocomplete="off" />
      </label>
      <label class="field">
        <span class="field__label">직무</span>
        <select name="role">
          ${Object.entries(ROLE_LABELS)
            .map(([role, label]) => `<option value="${role}">${label}</option>`)
            .join('')}
        </select>
      </label>
      <p class="field__hint">직무를 바꾸면 사용할 LLM 프로파일도 함께 바뀝니다.</p>
    `;
  }

  show(employee: Employee): void {
    this.employeeId = employee.id;
    (this.body.querySelector('[name="name"]') as HTMLInputElement).value = employee.name;
    (this.body.querySelector('[name="role"]') as HTMLSelectElement).value = employee.role;
    this.open();
  }

  protected async submit(): Promise<Employee> {
    const name = (this.body.querySelector('[name="name"]') as HTMLInputElement).value.trim();
    const role = (this.body.querySelector('[name="role"]') as HTMLSelectElement).value as Role;
    return updateEmployee(this.employeeId, { name, role });
  }
}
