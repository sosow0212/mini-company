/**
 * store는 서버가 준 값을 갈아끼우기만 한다. 계산하거나 추론하면 화면과 DB가 갈라진다.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Employee, LedgerSummary, OfficeEvent, OfficeSnapshot } from '../src/api/types';
import { OfficeStore } from '../src/state/officeStore';

const EMPLOYEE: Employee = {
  id: 'e1',
  name: '수집가 노아',
  role: 'COLLECTOR',
  status: 'OFFLINE',
  desk: { x: -4, y: 0, z: 0 },
  currentTaskId: null,
  llmProfile: 'structured',
  hiredAt: '2026-08-04T00:00:00Z',
};

const LEDGER: LedgerSummary = {
  period: 'monthly',
  start: '2026-08-01T00:00:00Z',
  end: '2026-09-01T00:00:00Z',
  totals: { REVENUE: '0', COST: '0', LLM_COST: '0', VIEWS: '0', SUBSCRIBERS: '0' },
  net: '0',
};

function snapshot(employees: readonly Employee[] = [EMPLOYEE]): OfficeSnapshot {
  return { employees, ledger: LEDGER };
}

function statusEvent(status: Employee['status'], taskId: string | null = null): OfficeEvent {
  return {
    type: 'employee.status_changed',
    data: { employeeId: 'e1', status, currentTaskId: taskId },
  };
}

function activityEvent(message: string, occurredAt = '2026-08-05T12:00:00Z'): OfficeEvent {
  return {
    type: 'activity.created',
    data: { employeeId: 'e1', taskId: 't1', level: 'INFO', message, occurredAt },
  };
}

describe('OfficeStore', () => {
  let store: OfficeStore;

  beforeEach(() => {
    store = new OfficeStore();
  });

  describe('스냅샷', () => {
    it('직원과 원장을 채운다', () => {
      store.replaceWithSnapshot(snapshot());

      expect(store.listEmployees()).toHaveLength(1);
      expect(store.ledger()?.net).toBe('0');
    });

    it('사라진 직원을 제거한다', () => {
      store.replaceWithSnapshot(snapshot());
      store.replaceWithSnapshot(snapshot([]));

      expect(store.listEmployees()).toHaveLength(0);
    });

    it('재연결 시 말풍선이 깜빡이지 않게 최근 활동을 유지한다', () => {
      store.replaceWithSnapshot(snapshot());
      store.apply(activityEvent('수집 준비 완료'));

      store.replaceWithSnapshot(snapshot());

      expect(store.findEmployee('e1')?.recentActivities.at(0)?.message).toBe('수집 준비 완료');
    });
  });

  describe('상태 변경 이벤트', () => {
    it('직원 상태와 현재 작업을 갈아끼운다', () => {
      store.replaceWithSnapshot(snapshot());

      store.apply(statusEvent('WORKING', 't1'));

      const view = store.findEmployee('e1');
      expect(view?.employee.status).toBe('WORKING');
      expect(view?.employee.currentTaskId).toBe('t1');
    });

    it('다른 필드는 건드리지 않는다', () => {
      store.replaceWithSnapshot(snapshot());

      store.apply(statusEvent('WORKING'));

      const view = store.findEmployee('e1');
      expect(view?.employee.name).toBe('수집가 노아');
      expect(view?.employee.desk).toEqual({ x: -4, y: 0, z: 0 });
      expect(view?.employee.llmProfile).toBe('structured');
    });

    it('모르는 직원의 이벤트는 버린다', () => {
      // 스냅샷이 진실이다. 이벤트로 직원을 만들면 반쪽 데이터가 화면에 남는다.
      store.replaceWithSnapshot(snapshot());

      store.apply({
        type: 'employee.status_changed',
        data: { employeeId: 'unknown', status: 'WORKING', currentTaskId: null },
      });

      expect(store.listEmployees()).toHaveLength(1);
      expect(store.findEmployee('unknown')).toBeUndefined();
    });
  });

  describe('활동 이벤트', () => {
    it('최신 활동이 앞에 온다', () => {
      store.replaceWithSnapshot(snapshot());

      store.apply(activityEvent('첫째', '2026-08-05T12:00:00Z'));
      store.apply(activityEvent('둘째', '2026-08-05T12:00:01Z'));

      const messages = store.findEmployee('e1')?.recentActivities.map((a) => a.message);
      expect(messages).toEqual(['둘째', '첫째']);
    });

    it('최근 3건만 남긴다', () => {
      store.replaceWithSnapshot(snapshot());

      for (const index of [1, 2, 3, 4, 5]) {
        store.apply(activityEvent(`활동 ${index}`, `2026-08-05T12:00:0${index}Z`));
      }

      const view = store.findEmployee('e1');
      expect(view?.recentActivities).toHaveLength(3);
      expect(view?.recentActivities.at(0)?.message).toBe('활동 5');
    });
  });

  describe('원장 이벤트', () => {
    it('요약을 통째로 갈아끼운다', () => {
      store.replaceWithSnapshot(snapshot());

      store.apply({
        type: 'ledger.summary_updated',
        data: { ...LEDGER, totals: { ...LEDGER.totals, REVENUE: '82860000' }, net: '82860000' },
      });

      expect(store.ledger()?.totals.REVENUE).toBe('82860000');
      expect(store.ledger()?.net).toBe('82860000');
    });

    it('서버가 준 net을 그대로 보관한다', () => {
      // 프론트가 net을 다시 계산하면 서버와 달라질 수 있다.
      store.replaceWithSnapshot(snapshot());

      store.apply({
        type: 'ledger.summary_updated',
        data: { ...LEDGER, totals: { ...LEDGER.totals, REVENUE: '100', COST: '30' }, net: '70' },
      });

      expect(store.ledger()?.net).toBe('70');
    });
  });

  describe('구독', () => {
    it('변경마다 알린다', () => {
      const listener = vi.fn();
      store.subscribe(listener);

      store.replaceWithSnapshot(snapshot());
      store.apply(statusEvent('WORKING'));

      expect(listener).toHaveBeenCalledTimes(2);
    });

    it('해지하면 더 알리지 않는다', () => {
      const listener = vi.fn();
      const unsubscribe = store.subscribe(listener);

      unsubscribe();
      store.replaceWithSnapshot(snapshot());

      expect(listener).not.toHaveBeenCalled();
    });
  });
});
