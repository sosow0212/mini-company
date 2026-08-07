/**
 * 원장 패널 (Ledger Panel) — 서버가 계산한 수치 문자열만 렌더링합니다 (ADR-006 준수).
 */

import type { LedgerCategory, LedgerSummary } from '../api/types';
import { categoryLabel, withThousandsSeparators } from './format';

const ROWS: readonly LedgerCategory[] = [
  'REVENUE',
  'COST',
  'LLM_COST',
  'VIEWS',
  'SUBSCRIBERS',
];
const CURRENCY_ROWS = new Set<LedgerCategory>(['REVENUE', 'COST', 'LLM_COST']);

export class LedgerPanel {
  private readonly netValue: HTMLElement;
  private readonly netSign: HTMLElement;
  private readonly rows = new Map<LedgerCategory, HTMLElement>();

  constructor(private readonly host: HTMLElement) {
    this.host.innerHTML = `
      <header class="panel__head">
        <h2 class="panel__title">📊 원장 요약</h2>
        <span class="panel__hint" data-period>—</span>
      </header>
      <div class="figure">
        <span class="figure__label">순손익</span>
        <p class="figure__value"><span data-net-sign class="figure__sign"></span><span data-net>—</span></p>
      </div>
      <dl class="ledger-rows">
        ${ROWS.map(
          (category) => `
          <div class="ledger-row" data-row="${category}">
            <dt>${categoryLabel(category)}</dt>
            <dd data-value>—</dd>
          </div>`,
        ).join('')}
      </dl>
    `;

    this.netValue = this.require('[data-net]');
    this.netSign = this.require('[data-net-sign]');
    for (const category of ROWS) {
      this.rows.set(category, this.require(`[data-row="${category}"] [data-value]`));
    }
  }

  render(summary: LedgerSummary | null): void {
    if (summary === null) return;

    this.require('[data-period]').textContent = summary.period.toUpperCase();
    this.netValue.textContent = withThousandsSeparators(summary.net);

    const negative = summary.net.startsWith('-');
    this.netSign.textContent = negative ? '' : '+';
    this.netValue.parentElement?.setAttribute('data-negative', String(negative));

    for (const [category, element] of this.rows) {
      const raw = summary.totals[category];
      element.textContent =
        raw === undefined
          ? '—'
          : withThousandsSeparators(raw) + (CURRENCY_ROWS.has(category) ? '' : '회');
    }
  }

  private require(selector: string): HTMLElement {
    const element = this.host.querySelector<HTMLElement>(selector);
    if (element === null) throw new Error(`원장 패널 요소를 찾을 수 없다: ${selector}`);
    return element;
  }
}
