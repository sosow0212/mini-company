/**
 * 네임태그 — 아바타 머리 위에 항상 떠 있는 신원 라벨.
 *
 * 말풍선과 다르다. 말풍선은 사건이 있을 때만 잠깐 뜨고 사라지지만, 네임태그는 상주해야
 * "누가 누군지"를 시선 이동 없이 알 수 있다. 그래서 폭을 최소로 잡고 직무는 3글자
 * 약어로 줄인다 — 이름을 밀어내면 정작 필요한 정보가 가려진다.
 */

import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { Employee } from '../api/types';
import { roleAbbreviation, roleKorean } from './format';

const TAG_HEIGHT_Y = 1.78;

export class NameTag {
  readonly label: CSS2DObject;
  private readonly element: HTMLDivElement;

  constructor(employee: Employee) {
    this.element = document.createElement('div');
    this.element.className = 'nametag';
    this.element.title = `${employee.name} · ${roleKorean(employee.role)}`;
    this.element.innerHTML = `
      <span class="nametag__role">${roleAbbreviation(employee.role)}</span>
      <span class="nametag__name"></span>
    `;
    // 이름은 서버 문자열이므로 textContent로 넣는다.
    const name = this.element.querySelector('.nametag__name');
    if (name !== null) name.textContent = employee.name;

    this.label = new CSS2DObject(this.element);
    this.label.position.set(0, TAG_HEIGHT_Y, 0);
    this.setStatus(employee.status);
  }

  /** 상태를 태그 테두리에도 반영한다 — 아바타 링과 같은 색이라 시선이 이어진다. */
  setStatus(status: Employee['status']): void {
    this.element.dataset.status = status;
  }
}
