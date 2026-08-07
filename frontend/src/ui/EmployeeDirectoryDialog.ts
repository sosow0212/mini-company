/**
 * 직원 목록 (Employee Directory) 다이얼로그.
 *
 * 상단바 [👥 직원 목록] 클릭 시 열리며,
 * 현재 채용된 모든 AI 직원 카드를 그리드로 보여주고
 * 선택 시 바로 직원 상세 슬라이드오버 드로어를 띄워줍니다.
 */

import type { Employee } from '../api/types';
import { ROLE_LABELS } from '../api/types';

export class EmployeeDirectoryDialog {
  private readonly dialog: HTMLDialogElement;
  private readonly grid: HTMLElement;
  private employees: readonly Employee[] = [];
  private onSelectEmployee: ((employee: Employee) => void) | null = null;
  private onHireClick: (() => void) | null = null;

  constructor() {
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'dialog';
    this.dialog.style.width = 'min(42rem, calc(100vw - 2rem))';
    this.dialog.innerHTML = `
      <div class="dialog__form">
        <header class="dialog__head">
          <h2 class="dialog__title">👥 AI 직원 디렉토리</h2>
          <button type="button" class="icon-button" data-close aria-label="닫기">✕</button>
        </header>

        <div class="dialog__body">
          <p class="dialog__lead">
            채용된 AI 직원 목록입니다. 직원을 선택하면 상세 정보 및 수행 업무 이력을 확인할 수 있습니다.
          </p>
          <div class="directory-grid" data-grid></div>
        </div>

        <footer class="dialog__foot" style="justify-content: space-between; align-items: center;">
          <button type="button" class="button button--primary" data-hire>+ 신규 직원 채용</button>
          <button type="button" class="button button--ghost" data-close>닫기</button>
        </footer>
      </div>
    `;
    document.body.append(this.dialog);

    this.grid = this.dialog.querySelector('[data-grid]') as HTMLElement;

    // 닫기 버튼 이벤트
    for (const button of this.dialog.querySelectorAll('[data-close]')) {
      button.addEventListener('click', () => this.close());
    }

    // 신규 채용 버튼 이벤트
    const hireBtn = this.dialog.querySelector('[data-hire]');
    hireBtn?.addEventListener('click', () => {
      this.close();
      this.onHireClick?.();
    });

    // 직원 카드 클릭 이벤트 핸들링
    this.grid.addEventListener('click', (event) => {
      const card = (event.target as HTMLElement).closest<HTMLElement>('[data-employee-id]');
      if (card === null) return;
      const employeeId = card.dataset.employeeId;
      const found = this.employees.find((emp) => emp.id === employeeId);
      if (found) {
        this.close();
        this.onSelectEmployee?.(found);
      }
    });
  }

  setEmployees(employees: readonly Employee[]): void {
    this.employees = employees;
    this.render();
  }

  setOnSelectEmployee(handler: (employee: Employee) => void): void {
    this.onSelectEmployee = handler;
  }

  setOnHireClick(handler: () => void): void {
    this.onHireClick = handler;
  }

  open(): void {
    this.render();
    this.dialog.showModal();
  }

  close(): void {
    this.dialog.close();
  }

  private render(): void {
    if (this.employees.length === 0) {
      this.grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 2rem 0; color: var(--text-dim);">
          채용된 AI 직원이 없습니다. 하단의 '+ 신규 직원 채용' 버튼으로 첫 직원을 배치해보세요!
        </div>
      `;
      return;
    }

    this.grid.innerHTML = this.employees
      .map((employee) => {
        return `
          <div class="employee-card" data-employee-id="${employee.id}">
            <div class="employee-card__head">
              <h3 class="employee-card__name">${escape(employee.name)}</h3>
              <span class="employee-card__role">${ROLE_LABELS[employee.role]}</span>
            </div>
            <div>
              <span class="status-chip" data-status="${employee.status}">${employee.status}</span>
            </div>
            <p style="margin: 0; font-size: var(--text-tag); color: var(--text-faint);">
              프로필: ${escape(employee.llmProfile)}
            </p>
          </div>
        `;
      })
      .join('');
  }
}

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
