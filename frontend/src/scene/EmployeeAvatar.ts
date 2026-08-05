/**
 * 직원 1명 = 캐릭터 1개.
 *
 * 여전히 GLTF를 쓰지 않는다(§12). 대신 프리미티브를 홀로그램처럼 다룬다:
 * 반투명 캡슐 + 발광 코어 + 발밑 상태 링. 형태를 정교하게 만드는 대신 **빛으로** 존재감을
 * 낸다 — 모델링에 시간을 쓰기 시작하면 프로젝트가 거기서 멈춘다.
 *
 * 상태를 가장 강하게 말하는 건 **발밑 링**이다. 몸 색만으로는 멀리서 구분이 어렵고,
 * 링은 바닥에 붙어 있어 아바타가 겹쳐도 보인다. bloom이 이 링을 잡아 번지게 한다.
 */

import {
  CapsuleGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  RingGeometry,
  SphereGeometry,
  type Object3D,
} from 'three';
import type { Employee, EmployeeStatus } from '../api/types';
import { statusColor, statusOpacity } from './palette';
import { DESK_SURFACE_Y } from './OfficeLayout';

const BODY_HEIGHT = 0.46;
const BODY_RADIUS = 0.17;
const HEAD_RADIUS = 0.14;
const RING_INNER = 0.26;
const RING_OUTER = 0.34;

/** 책상 뒤에 앉은 높이. 상체만 책상 위로 나온다. */
const SEAT_Y = DESK_SURFACE_Y - 0.2;
const CHAIR_OFFSET_Z = 0.66;

const COLOR_LERP_PER_SECOND = 6;
const BOB_AMPLITUDE = 0.02;
const BOB_SPEED = 2.2;
const RING_SPIN_SPEED = 0.9;
/** 일하는 중일 때 코어가 숨쉬는 폭. 정지된 아바타 사이에서 이게 시선을 끈다. */
const PULSE_RANGE = 0.5;

export class EmployeeAvatar {
  readonly object: Group;
  private readonly bodyMaterial: MeshStandardMaterial;
  private readonly coreMaterial: MeshStandardMaterial;
  private readonly ringMaterial: MeshStandardMaterial;
  private readonly ring: Mesh;
  private status: EmployeeStatus;
  private readonly baseY: number;

  constructor(employee: Employee) {
    this.status = employee.status;
    this.object = new Group();
    this.object.position.set(employee.desk.x, SEAT_Y, employee.desk.z + CHAIR_OFFSET_Z);
    this.baseY = SEAT_Y;
    // Raycaster가 맞춘 메시에서 직원을 되찾을 수 있게 한다.
    this.object.userData.employeeId = employee.id;

    const color = statusColor(employee.status);
    const opacity = statusOpacity(employee.status);

    // 몸통: 반투명 유리. 뒤가 살짝 보여야 홀로그램처럼 읽힌다.
    this.bodyMaterial = new MeshStandardMaterial({
      color: 0x1b2233,
      emissive: color.clone(),
      emissiveIntensity: 0.22,
      roughness: 0.28,
      metalness: 0.5,
      transparent: true,
      opacity: 0.62 * opacity,
    });
    const body = new Mesh(new CapsuleGeometry(BODY_RADIUS, BODY_HEIGHT, 6, 18), this.bodyMaterial);
    body.position.y = BODY_HEIGHT / 2 + BODY_RADIUS;
    body.castShadow = true;

    // 코어: 몸 안에서 빛나는 구. 상태색을 그대로 뿜는다.
    this.coreMaterial = new MeshStandardMaterial({
      color: 0x000000,
      emissive: color.clone(),
      emissiveIntensity: 1.5,
      transparent: true,
      opacity,
    });
    const core = new Mesh(new SphereGeometry(HEAD_RADIUS, 20, 16), this.coreMaterial);
    core.position.y = BODY_HEIGHT + BODY_RADIUS * 1.7;

    // 발밑 링: 상태의 주 신호. 바닥에 눕혀 아바타가 겹쳐도 보이게 한다.
    this.ringMaterial = new MeshStandardMaterial({
      color: 0x000000,
      emissive: color.clone(),
      emissiveIntensity: 2.1,
      transparent: true,
      opacity: 0.9 * opacity,
    });
    this.ring = new Mesh(new RingGeometry(RING_INNER, RING_OUTER, 40), this.ringMaterial);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.012;

    this.object.add(body, core, this.ring);
  }

  setStatus(status: EmployeeStatus): void {
    this.status = status;
  }

  /** 매 프레임 호출. delta 기반이라 프레임레이트가 흔들려도 속도가 같다. */
  update(delta: number, elapsed: number, motionEnabled: boolean): void {
    const target = statusColor(this.status);
    const factor = Math.min(1, delta * COLOR_LERP_PER_SECOND);
    for (const material of [this.bodyMaterial, this.coreMaterial, this.ringMaterial]) {
      material.emissive.lerp(target, factor);
    }

    const targetOpacity = statusOpacity(this.status);
    this.coreMaterial.opacity += (targetOpacity - this.coreMaterial.opacity) * factor;
    this.bodyMaterial.opacity += (0.62 * targetOpacity - this.bodyMaterial.opacity) * factor;
    this.ringMaterial.opacity += (0.9 * targetOpacity - this.ringMaterial.opacity) * factor;

    const working = this.status === 'WORKING' && motionEnabled;
    // 정지 상태에서도 링은 남지만 회전·맥동은 멈춘다. 움직임 자체가 "일하는 중" 신호다.
    this.coreMaterial.emissiveIntensity = working
      ? 1.5 + Math.sin(elapsed * BOB_SPEED * 2) * PULSE_RANGE
      : 1.1;
    if (working) this.ring.rotation.z = elapsed * RING_SPIN_SPEED;
    this.object.position.y = this.baseY + (working ? Math.sin(elapsed * BOB_SPEED) * BOB_AMPLITUDE : 0);
  }

  dispose(): void {
    for (const material of [this.bodyMaterial, this.coreMaterial, this.ringMaterial]) {
      material.dispose();
    }
    for (const child of this.object.children) {
      if (child instanceof Mesh) child.geometry.dispose();
    }
  }

  get pickables(): readonly Object3D[] {
    return this.object.children;
  }
}
