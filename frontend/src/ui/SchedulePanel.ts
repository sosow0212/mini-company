/**
 * 반복 지시 — "매일 몇 시에 누구에게 무엇을".
 *
 * 등록하면 그 시각에 백엔드 틱 루프가 QUEUED 작업을 만들고, 에이전트가 집어간다.
 * 사람이 직접 시킨 일과 완전히 같은 경로다 — 다르게 돌면 "스케줄로 돈 것만 이상한"
 * 상태가 생긴다.
 *
 * 끄기(토글)와 지우기를 나눈 이유: 잠시 멈추는 것과 규칙을 버리는 것은 다르다.
 * 매일 도는 지시를 며칠 쉬려고 지웠다가 다시 만드는 건 번거롭다.
 */

import { deleteSchedule, fetchSchedules, setScheduleEnabled } from '../api/client';
import type { Employee, Schedule } from '../api/types';
import { WORKFLOWS } from '../api/types';

const REFRESH_MS = 30_000;

export class SchedulePanel {
  private schedules: readonly Schedule[] = [];
  private employeeNames = new Map<string, string>();
  private onAddHandler: (() => void) | null = null;

  constructor(private readonly host: HTMLElement) {
    this.host.addEventListener('click', (event) => {
      const target = event.target as HTMLElement;
      if (target.closest('[data-add-schedule]') !== null) {
        this.onAddHandler?.();
        return;
      }
      const toggle = target.closest<HTMLElement>('[data-toggle-schedule]');
      if (toggle !== null) {
        void this.toggle(toggle.dataset.toggleSchedule as string, toggle.dataset.next === 'on');
        return;
      }
      const remove = target.closest<HTMLElement>('[data-delete-schedule]');
      if (remove !== null) void this.remove(remove.dataset.deleteSchedule as string);
    });
    this.render();
    // 스케줄은 자주 바뀌지 않는다. lastRunAt 갱신을 반영할 정도로만 돈다.
    window.setInterval(() => void this.refresh(), REFRESH_MS);
  }

  setOnAdd(handler: () => void): void {
    this.onAddHandler = handler;
  }

  setEmployees(employees: readonly Employee[]): void {
    this.employeeNames = new Map(employees.map((employee) => [employee.id, employee.name]));
    this.render();
  }

  async refresh(): Promise<void> {
    try {
      this.schedules = await fetchSchedules();
      this.render();
    } catch {
      // 폴링 실패는 조용히 넘긴다. 연결 배지가 이미 끊김을 알린다.
    }
  }

  private async toggle(id: string, enabled: boolean): Promise<void> {
    try {
      await setScheduleEnabled(id, enabled);
    } catch {
      // 이미 지워진 경우다. 새로고침하면 목록에서 사라진다.
    }
    await this.refresh();
  }

  private async remove(id: string): Promise<void> {
    if (!window.confirm('이 반복 지시를 삭제할까요?')) return;
    try {
      await deleteSchedule(id);
    } catch {
      // 위와 같다.
    }
    await this.refresh();
  }

  private render(): void {
    const active = this.schedules.filter((schedule) => schedule.enabled).length;
    this.host.innerHTML = `
      <header class="panel__head">
        <h2 class="panel__title">반복 지시</h2>
        <div class="panel__head-actions">
          ${active > 0 ? `<span class="panel__count">${String(active)}건 활성</span>` : ''}
          <button type="button" class="link-button" data-add-schedule>+ 추가</button>
        </div>
      </header>
      ${this.listMarkup()}
    `;
  }

  private listMarkup(): string {
    if (this.schedules.length === 0) {
      return `<p class="panel__empty">
        정해진 시각에 알아서 일하게 하려면 <strong>+ 추가</strong>를 누르세요.<br />
        예: 매일 09:00 자료 수집
      </p>`;
    }
    return `<ul class="schedule-list">
      ${this.schedules.map((schedule) => this.itemMarkup(schedule)).join('')}
    </ul>`;
  }

  private itemMarkup(schedule: Schedule): string {
    const who = this.employeeNames.get(schedule.employeeId) ?? '(퇴사)';
    const what =
      WORKFLOWS.find((workflow) => workflow.kind === schedule.kind)?.label ?? schedule.kind;
    const time = `${pad(schedule.hour)}:${pad(schedule.minute)}`;
    return `<li data-enabled="${String(schedule.enabled)}">
      <div class="schedule-list__main">
        <span class="schedule-list__time">${time}</span>
        <div class="schedule-list__what">
          <span>${escape(who)} · ${escape(what)}</span>
          ${
            schedule.title === null
              ? ''
              : `<span class="schedule-list__title">${escape(schedule.title)}</span>`
          }
        </div>
      </div>
      <div class="schedule-list__foot">
        <span>${lastRunLabel(schedule.lastRunAt)}</span>
        <div>
          <button type="button" class="link-button" data-toggle-schedule="${schedule.id}"
                  data-next="${schedule.enabled ? 'off' : 'on'}">
            ${schedule.enabled ? '끄기' : '켜기'}
          </button>
          <button type="button" class="link-button" data-delete-schedule="${schedule.id}">삭제</button>
        </div>
      </div>
    </li>`;
  }
}

function lastRunLabel(lastRunAt: string | null): string {
  if (lastRunAt === null) return '아직 실행된 적 없음';
  const when = new Date(lastRunAt);
  const today = new Date();
  const sameDay =
    when.getFullYear() === today.getFullYear() &&
    when.getMonth() === today.getMonth() &&
    when.getDate() === today.getDate();
  const time = `${pad(when.getHours())}:${pad(when.getMinutes())}`;
  return sameDay ? `오늘 ${time} 실행` : `${String(when.getMonth() + 1)}/${String(when.getDate())} ${time} 실행`;
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

function escape(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}
