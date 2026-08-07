/**
 * 지식 베이스 — 직원들이 수집해 적재한 자료.
 *
 * 이 패널이 없으면 "수집 완료"라는 활동 로그만 보이고 **무엇이 들어갔는지** 알 수 없다.
 * RAG 챗봇이 답변에 쓰는 근거가 바로 이 목록이므로, 여기가 비어 있으면 챗봇도
 * "자료에 없습니다"만 답한다 — 그 인과가 화면에서 보여야 한다.
 *
 * 본문 전체는 내려받지 않는다(서버가 길이만 준다). 목록 화면에 2MB 텍스트가 필요한
 * 경우는 없고, 청크 수·전략·인덱싱 시각이 "검색에 쓸 수 있는 상태인가"를 말해준다.
 */

import { fetchDocuments } from '../api/client';
import type { KnowledgeDocument } from '../api/types';
import { formatClockTime } from './format';

const REFRESH_MS = 10_000;
const VISIBLE_LIMIT = 8;

const SOURCE_LABELS: Readonly<Record<string, string>> = {
  WEB: '웹',
  FILE: '파일',
  API: 'API',
  MANUAL: '직접 입력',
};

export class KnowledgePanel {
  private documents: readonly KnowledgeDocument[] = [];
  private expanded: string | null = null;

  constructor(private readonly host: HTMLElement) {
    this.host.addEventListener('click', (event) => {
      const item = (event.target as HTMLElement).closest<HTMLElement>('[data-doc]');
      if (item === null) return;
      const id = item.dataset.doc as string;
      // 같은 항목을 다시 누르면 접는다.
      this.expanded = this.expanded === id ? null : id;
      this.render();
    });
    this.render();
    window.setInterval(() => void this.refresh(), REFRESH_MS);
  }

  async refresh(): Promise<void> {
    try {
      this.documents = await fetchDocuments(VISIBLE_LIMIT);
      this.render();
    } catch {
      // 폴링 실패는 조용히 넘긴다.
    }
  }

  private render(): void {
    this.host.innerHTML = `
      <header class="panel__head">
        <h2 class="panel__title">지식 베이스</h2>
        ${
          this.documents.length > 0
            ? `<span class="panel__count">${String(this.documents.length)}건</span>`
            : ''
        }
      </header>
      ${this.listMarkup()}
    `;
  }

  private listMarkup(): string {
    if (this.documents.length === 0) {
      return `<p class="panel__empty">
        적재된 자료가 없습니다.<br />직원에게 <strong>자료 수집</strong>을 시켜보세요.
      </p>`;
    }
    return `<ul class="doc-list">
      ${this.documents.map((document) => this.itemMarkup(document)).join('')}
    </ul>`;
  }

  private itemMarkup(document: KnowledgeDocument): string {
    const open = this.expanded === document.id;
    const indexed = document.indexedAt !== null;
    return `<li>
      <button type="button" class="doc-list__row" data-doc="${document.id}"
              aria-expanded="${String(open)}">
        <span class="doc-list__title">${escape(document.title)}</span>
        <span class="doc-list__badge" data-indexed="${String(indexed)}">
          ${indexed ? `청크 ${String(document.chunkCount)}` : '미인덱싱'}
        </span>
      </button>
      ${open ? this.detailMarkup(document) : ''}
    </li>`;
  }

  private detailMarkup(document: KnowledgeDocument): string {
    const meta = document.metadata;
    const rows: [string, string][] = [
      ['출처', `${SOURCE_LABELS[document.sourceType] ?? document.sourceType} · ${document.contentType}`],
      ['수집', formatClockTime(document.collectedAt)],
      ['청킹', `${document.chunkingStrategy} · ${String(document.textLength)}자`],
    ];
    if (meta.author !== null) rows.push(['작성자', meta.author]);
    if (meta.siteName !== null) rows.push(['사이트', meta.siteName]);
    if (meta.keywords.length > 0) rows.push(['키워드', meta.keywords.join(', ')]);

    return `<div class="doc-list__detail">
      ${
        meta.description === null
          ? ''
          : `<p class="doc-list__desc">${escape(meta.description)}</p>`
      }
      <dl>
        ${rows
          .map(([label, value]) => `<dt>${label}</dt><dd>${escape(value)}</dd>`)
          .join('')}
      </dl>
      ${
        document.sourceUrl === null
          ? ''
          : `<a class="doc-list__link" href="${escapeAttr(document.sourceUrl)}"
                target="_blank" rel="noreferrer noopener">원문 열기 ↗</a>`
      }
    </div>`;
  }
}

function escape(value: string): string {
  const element = window.document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}

function escapeAttr(value: string): string {
  return escape(value).replaceAll('"', '&quot;');
}
