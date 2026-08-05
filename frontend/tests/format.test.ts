/**
 * 표기 변환. 프론트가 서버 숫자를 왜곡하지 않는지가 검증 대상이다(ADR-006).
 */

import { describe, expect, it } from 'vitest';
import { categoryLabel, withThousandsSeparators } from '../src/ui/format';

describe('withThousandsSeparators', () => {
  it.each([
    ['0', '0'],
    ['82860000', '82,860,000'],
    ['1000', '1,000'],
    ['999', '999'],
    ['-1240000', '-1,240,000'],
    ['82860000.55', '82,860,000.55'],
    ['-0.3', '-0.3'],
    ['0.0000001', '0.0000001'],
  ])('%s → %s', (input, expected) => {
    expect(withThousandsSeparators(input)).toBe(expected);
  });

  it('소수부에는 구분자를 넣지 않는다', () => {
    expect(withThousandsSeparators('1234.567891')).toBe('1,234.567891');
  });

  it('큰 수를 지수 표기로 바꾸지 않는다', () => {
    // Number()를 거치면 1e21에서 지수 표기가 된다. 문자열 조작이라 그 문제가 없다.
    expect(withThousandsSeparators('1000000000000000000000')).toBe(
      '1,000,000,000,000,000,000,000',
    );
  });

  it('정밀도를 잃지 않는다', () => {
    // double로 변환하면 마지막 자리가 깎이는 값.
    const exact = '9007199254740993';
    expect(withThousandsSeparators(exact).replace(/,/g, '')).toBe(exact);
  });

  it('예상 밖 형식은 서버 값을 그대로 보여준다', () => {
    // 임의로 고치면 화면과 원장이 갈라졌을 때 원인을 추적할 수 없다.
    expect(withThousandsSeparators('N/A')).toBe('N/A');
    expect(withThousandsSeparators('1e5')).toBe('1e5');
    expect(withThousandsSeparators('')).toBe('');
  });
});

describe('categoryLabel', () => {
  it('SCREAMING_SNAKE를 화면용으로 바꾼다', () => {
    expect(categoryLabel('LLM_COST')).toBe('llm cost');
    expect(categoryLabel('REVENUE')).toBe('revenue');
  });
});
