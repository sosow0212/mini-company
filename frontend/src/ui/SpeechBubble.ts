/**
 * 말풍선 — 아바타에 매달리는 DOM 라벨.
 *
 * 내용의 원천은 `Activity.message`다. 여기에 수치를 조립해 넣지 않는다 — 활동 메시지에
 * 숫자가 없어야 한다는 규칙(§7.3)을 프론트가 우회하면 그 방어선이 무의미해진다.
 */

import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { ActivityLevel } from '../api/types';

const BUBBLE_HEIGHT_Y = 2.08;
/** 이 시간이 지난 활동은 말풍선에서 감춘다. 오래된 말풍선이 남아 있으면 지금 상태로 오독된다. */
const VISIBLE_MS = 12_000;

export class SpeechBubble {
  readonly label: CSS2DObject;
  private readonly element: HTMLDivElement;
  private shownAt = 0;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'speech-bubble';
    this.element.setAttribute('aria-live', 'polite');
    this.label = new CSS2DObject(this.element);
    this.label.position.set(0, BUBBLE_HEIGHT_Y, 0);
    this.hide();
  }

  show(message: string, level: ActivityLevel, occurredAtMs: number): void {
    this.element.textContent = message;
    this.element.dataset.level = level;
    this.element.classList.add('is-visible');
    this.shownAt = occurredAtMs;
  }

  hide(): void {
    this.element.classList.remove('is-visible');
    this.element.textContent = '';
  }

  /** 시간이 지난 말풍선을 스스로 접는다. store를 건드리지 않는다 — 표시 관심사다. */
  expireIfStale(nowMs: number): void {
    if (this.shownAt === 0) return;
    if (nowMs - this.shownAt > VISIBLE_MS) {
      this.shownAt = 0;
      this.hide();
    }
  }
}
