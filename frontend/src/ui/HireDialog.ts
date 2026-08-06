/**
 * 채용 폼.
 *
 * 책상 좌표와 LLM 프로파일 입력란이 없다 — 서버가 정한다. 3D 좌표는 사용자가 알 바가
 * 아니고, 프로파일은 직무에서 파생된다(§8.3). 고르게 두면 배정 규칙이 UI와 서버
 * 두 곳으로 갈라진다.
 */

import { hireEmployee } from '../api/client';
import type { Employee, Role } from '../api/types';
import { ROLE_LABELS } from '../api/types';
import { FormDialog } from './FormDialog';

export class HireDialog extends FormDialog<Employee> {
  constructor() {
    super('직원 채용', '채용하기');
    this.body.innerHTML = `
      <label class="field">
        <span class="field__label">이름</span>
        <input name="name" type="text" maxlength="30" required
               placeholder="예: 분석가 리아" autocomplete="off" />
      </label>
      <label class="field">
        <span class="field__label">직무</span>
        <select name="role">
          ${Object.entries(ROLE_LABELS)
            .map(([role, label]) => `<option value="${role}">${label}</option>`)
            .join('')}
        </select>
      </label>
      <p class="field__hint">
        직무에 따라 사용할 LLM 프로파일과 책상 자리가 자동으로 정해집니다.
      </p>
    `;
  }

  show(): void {
    (this.body.querySelector('[name="name"]') as HTMLInputElement).value = '';
    this.open();
  }

  protected async submit(): Promise<Employee> {
    const name = (this.body.querySelector('[name="name"]') as HTMLInputElement).value.trim();
    const role = (this.body.querySelector('[name="role"]') as HTMLSelectElement).value as Role;
    return hireEmployee(name, role);
  }
}
