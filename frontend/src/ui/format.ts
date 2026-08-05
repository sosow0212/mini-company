/**
 * 표기 변환만. 계산은 없다.
 *
 * `Number()`를 거치지 않는 이유: 서버가 Decimal로 만든 문자열을 double로 바꾸면
 * 정밀도가 깎인다. 천 단위 구분은 문자열 조작으로 충분하다(ADR-006이 허용하는 범위).
 */

import type { Role } from '../api/types';

const DECIMAL_PATTERN = /^(-?)(\d+)(\.\d+)?$/;
const THOUSANDS = /\B(?=(\d{3})+(?!\d))/g;

export function withThousandsSeparators(value: string): string {
  const match = DECIMAL_PATTERN.exec(value);
  // 예상 밖 형식이면 서버 값을 그대로 보여준다. 임의로 고치면 원인 추적이 어려워진다.
  if (match === null) return value;
  const [, sign = '', whole = '', fraction = ''] = match;
  return `${sign}${whole.replace(THOUSANDS, ',')}${fraction}`;
}

/** 원장 카테고리 라벨. 화면에 SCREAMING_SNAKE를 그대로 내보내지 않는다. */
export function categoryLabel(category: string): string {
  return category.toLowerCase().replace(/_/g, ' ');
}

/**
 * 직무 배지용 3글자 약어.
 *
 * 네임태그는 아바타 위에 떠 있어 폭이 좁다. 직무 전체를 쓰면 이름을 밀어내므로 약어를
 * 쓰고, 툴팁(title)에 전체 이름을 남긴다.
 */
const ROLE_ABBREVIATION: Readonly<Record<Role, string>> = {
  COLLECTOR: 'COL',
  WRITER: 'WRI',
  ANALYST: 'ANL',
  TRADER: 'TRD',
  ENGINEER: 'ENG',
};

const ROLE_KOREAN: Readonly<Record<Role, string>> = {
  COLLECTOR: '수집',
  WRITER: '작성',
  ANALYST: '분석',
  TRADER: '트레이딩',
  ENGINEER: '엔지니어',
};

export function roleAbbreviation(role: Role): string {
  return ROLE_ABBREVIATION[role] ?? role.slice(0, 3);
}

export function roleKorean(role: Role): string {
  return ROLE_KOREAN[role] ?? role.toLowerCase();
}

export function formatClockTime(isoString: string): string {
  const parsed = new Date(isoString);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}
