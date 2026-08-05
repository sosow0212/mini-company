/**
 * 서버 스냅샷 보관소.
 *
 * **계산하지 않는다.** 이벤트가 준 값으로 갈아끼우기만 한다(ADR-006). 금액을 더하거나
 * 상태를 추론하는 코드가 여기 들어가는 순간 화면과 DB가 갈라지고, 어느 쪽이 맞는지
 * 판단할 근거가 사라진다.
 */

import type { Activity, Employee, LedgerSummary, OfficeEvent, OfficeSnapshot } from '../api/types';

/** 말풍선에 남겨둘 최근 활동 수. 오래된 것은 버린다 — 이력의 주인은 서버다. */
const RECENT_ACTIVITY_LIMIT = 3;

export interface EmployeeView {
  readonly employee: Employee;
  readonly recentActivities: readonly Activity[];
}

type Listener = () => void;

export class OfficeStore {
  private employees = new Map<string, EmployeeView>();
  private ledgerSummary: LedgerSummary | null = null;
  private readonly listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** 진입 시와 재연결 직후에 호출된다. 기존 상태를 통째로 대체한다. */
  replaceWithSnapshot(snapshot: OfficeSnapshot): void {
    const previous = this.employees;
    this.employees = new Map(
      snapshot.employees.map((employee) => [
        employee.id,
        {
          employee,
          // 활동 로그는 스냅샷에 없다. 화면이 빈 말풍선으로 깜빡이지 않게 기존 것을 잇는다.
          recentActivities: previous.get(employee.id)?.recentActivities ?? [],
        },
      ]),
    );
    this.ledgerSummary = snapshot.ledger;
    this.notify();
  }

  apply(event: OfficeEvent): void {
    switch (event.type) {
      case 'employee.status_changed':
        this.patchEmployee(event.data.employeeId, (employee) => ({
          ...employee,
          status: event.data.status,
          currentTaskId: event.data.currentTaskId,
        }));
        break;
      case 'activity.created':
        this.pushActivity(event.data);
        break;
      case 'ledger.summary_updated':
        this.ledgerSummary = event.data;
        this.notify();
        break;
    }
  }

  setActivities(employeeId: string, activities: readonly Activity[]): void {
    const view = this.employees.get(employeeId);
    if (view === undefined) return;
    this.employees.set(employeeId, {
      ...view,
      recentActivities: activities.slice(0, RECENT_ACTIVITY_LIMIT),
    });
    this.notify();
  }

  listEmployees(): readonly EmployeeView[] {
    return [...this.employees.values()];
  }

  findEmployee(employeeId: string): EmployeeView | undefined {
    return this.employees.get(employeeId);
  }

  ledger(): LedgerSummary | null {
    return this.ledgerSummary;
  }

  private patchEmployee(employeeId: string, patch: (employee: Employee) => Employee): void {
    const view = this.employees.get(employeeId);
    // 모르는 직원의 이벤트는 버린다. 스냅샷이 진실이고, 다음 재연결에서 채워진다.
    if (view === undefined) return;
    this.employees.set(employeeId, { ...view, employee: patch(view.employee) });
    this.notify();
  }

  private pushActivity(activity: Omit<Activity, 'id'> & { readonly id?: string }): void {
    const view = this.employees.get(activity.employeeId);
    if (view === undefined) return;
    // 이벤트 페이로드에는 id가 없다. 목록 키로만 쓰이므로 발생 시각으로 대체한다.
    const entry: Activity = { id: activity.id ?? activity.occurredAt, ...activity };
    this.employees.set(activity.employeeId, {
      ...view,
      recentActivities: [entry, ...view.recentActivities].slice(0, RECENT_ACTIVITY_LIMIT),
    });
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
