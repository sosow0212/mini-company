/**
 * 재연결 백오프. 서버 재시작 시 모든 탭이 같은 순간에 몰리지 않아야 한다.
 */

import { describe, expect, it } from 'vitest';
import { backoffDelay } from '../src/api/socket';

describe('backoffDelay', () => {
  it('시도가 늘면 지연도 늘어난다', () => {
    const fixed = () => 1;
    const delays = [0, 1, 2, 3].map((attempt) => backoffDelay(attempt, fixed));

    expect(delays).toEqual([...delays].sort((a, b) => a - b));
    expect(new Set(delays).size).toBe(delays.length);
  });

  it('상한을 넘지 않는다', () => {
    expect(backoffDelay(50, () => 1)).toBeLessThanOrEqual(15_000);
  });

  it('첫 재시도는 즉시에 가깝다', () => {
    // 서버가 잠깐 끊긴 경우 화면이 오래 멈춰 있으면 안 된다.
    expect(backoffDelay(0, () => 1)).toBeLessThanOrEqual(500);
  });

  it('지터로 같은 시도에서도 값이 흩어진다', () => {
    const low = backoffDelay(4, () => 0);
    const high = backoffDelay(4, () => 1);

    expect(low).toBeLessThan(high);
    // 하한은 상한의 절반 — 몰림을 줄이면서도 재연결이 과하게 늦지 않는다.
    expect(low).toBeCloseTo(high / 2, -1);
  });

  it('항상 양수다', () => {
    for (const attempt of [0, 1, 5, 10]) {
      expect(backoffDelay(attempt, () => 0)).toBeGreaterThan(0);
    }
  });
});
