/**
 * 직원 1명 = 로봇 캐릭터 1개.
 *
 * 여전히 GLTF를 쓰지 않는다(§12). 프리미티브 조합이지만 "홀로그램"이 아니라 **책상에
 * 앉아 일하는 로봇**으로 그린다: 몸통은 직무색, 얼굴은 카메라을 향하고, 키보드 위로
 * 팔을 뻗는다. 일하는 중이면 타이핑하듯 팔이 움직인다 — 움직임 자체가 상태 신호다.
 *
 * 상태 색은 **안테나 끝의 전구**가 든다. 몸통을 상태색으로 칠하면 직원이 상태를
 * 바꿀 때마다 다른 캐릭터처럼 보인다. 정체성(직무색 몸통)은 고정하고 상태(전구)만
 * 바뀌어야 "누가" "어떤 상태인지"를 동시에 읽을 수 있다.
 */

import {
  CapsuleGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  SphereGeometry,
  type Object3D,
} from 'three';
import type { Employee, EmployeeStatus } from '../api/types';
import { roleColor, statusColor, statusOpacity } from './palette';
import { SEAT_OFFSET_Z } from './OfficeLayout';

const TORSO_RADIUS = 0.16;
const TORSO_LENGTH = 0.26;
const TORSO_Y = 0.78;
const HEAD_RADIUS = 0.17;
const HEAD_Y = 1.18;
const EYE_RADIUS = 0.03;
const EYE_Y = 1.2;
const EYE_Z = 0.16;
const EYE_SPACING = 0.062;
const ANTENNA_TIP_Y = 1.45;
const ARM_RADIUS = 0.045;
const ARM_LENGTH = 0.16;
const ARM_Y = 0.78;
const ARM_Z = 0.08;
const ARM_REACH_TILT = -1.0;

const COLOR_LERP_PER_SECOND = 6;
const TYPING_SPEED = 10;
const TYPING_AMPLITUDE = 0.1;
const HEAD_SWAY_SPEED = 1.4;
const HEAD_SWAY_AMPLITUDE = 0.05;
/** 눈 깜빡임 주기(초)와 깜빡이는 길이. 자리마다 위상이 달라 동시에 감지 않는다. */
const BLINK_CYCLE = 3.4;
const BLINK_LENGTH = 0.12;
/* 안테나 팁의 크기 맥동 폭. 색이 아니라 움직임으로 "일하는 중"을 알린다. */
const TIP_PULSE_SCALE = 0.22;

export class EmployeeAvatar {
  readonly object: Group;
  private readonly fadeMaterials: readonly (MeshStandardMaterial | MeshBasicMaterial)[];
  private readonly tipMaterial: MeshBasicMaterial;
  private readonly leftArm: Mesh;
  private readonly rightArm: Mesh;
  private readonly head: Mesh;
  private readonly eyes: readonly Mesh[];
  private readonly tip: Mesh;
  private status: EmployeeStatus;
  /** 자리 x좌표로 만든 위상. 직원마다 타이밍이 어긋나야 군집 로봇처럼 보이지 않는다. */
  private readonly phase: number;

  constructor(employee: Employee) {
    this.status = employee.status;
    this.phase = employee.desk.x * 1.7;
    this.object = new Group();
    this.object.position.set(employee.desk.x, 0, employee.desk.z + SEAT_OFFSET_Z);
    // Raycaster가 맞춘 메시에서 직원을 되찾을 수 있게 한다.
    this.object.userData.employeeId = employee.id;

    const identity = roleColor(employee.role);
    const bodyMaterial = new MeshStandardMaterial({
      color: identity,
      roughness: 0.55,
      transparent: true,
    });
    const headMaterial = new MeshStandardMaterial({
      color: 0xfbf2e4,
      roughness: 0.5,
      transparent: true,
    });
    const eyeMaterial = new MeshStandardMaterial({
      color: 0x2e2b26,
      roughness: 0.4,
      transparent: true,
    });
    const antennaMaterial = new MeshStandardMaterial({
      color: 0x8b8578,
      roughness: 0.5,
      transparent: true,
    });
    // 상태등 재질은 unlit이다 — 이유는 OfficeLayout의 Busylight 주석 참조.
    this.tipMaterial = new MeshBasicMaterial({
      color: statusColor(employee.status),
      transparent: true,
    });
    this.fadeMaterials = [bodyMaterial, headMaterial, eyeMaterial, antennaMaterial, this.tipMaterial];

    const torso = new Mesh(
      new CapsuleGeometry(TORSO_RADIUS, TORSO_LENGTH, 6, 18),
      bodyMaterial,
    );
    torso.position.y = TORSO_Y;
    torso.castShadow = true;

    this.head = new Mesh(new SphereGeometry(HEAD_RADIUS, 24, 18), headMaterial);
    this.head.position.y = HEAD_Y;
    this.head.castShadow = true;

    const eyes: Mesh[] = [];
    for (const side of [-1, 1]) {
      const eye = new Mesh(new SphereGeometry(EYE_RADIUS, 10, 8), eyeMaterial);
      eye.position.set(side * EYE_SPACING, EYE_Y - HEAD_Y, EYE_Z);
      this.head.add(eye);
      eyes.push(eye);
    }
    this.eyes = eyes;

    const antenna = new Mesh(new CylinderGeometry(0.014, 0.014, 0.1, 8), antennaMaterial);
    antenna.position.y = HEAD_RADIUS + 0.05;
    this.tip = new Mesh(new SphereGeometry(0.055, 14, 10), this.tipMaterial);
    this.tip.position.y = ANTENNA_TIP_Y - HEAD_Y;
    this.head.add(antenna, this.tip);

    this.leftArm = new Mesh(
      new CapsuleGeometry(ARM_RADIUS, ARM_LENGTH, 4, 10),
      bodyMaterial,
    );
    this.rightArm = this.leftArm.clone();
    this.leftArm.position.set(-(TORSO_RADIUS + 0.055), ARM_Y, ARM_Z);
    this.rightArm.position.set(TORSO_RADIUS + 0.055, ARM_Y, ARM_Z);
    this.leftArm.rotation.set(ARM_REACH_TILT, 0, 0.2);
    this.rightArm.rotation.set(ARM_REACH_TILT, 0, -0.2);

    this.object.add(torso, this.head, this.leftArm, this.rightArm);
    this.applyOpacity(statusOpacity(employee.status));
  }

  setStatus(status: EmployeeStatus): void {
    this.status = status;
  }

  /** 매 프레임 호출. delta 기반이라 프레임레이트가 흔들려도 속도가 같다. */
  update(delta: number, elapsed: number, motionEnabled: boolean): void {
    const factor = Math.min(1, delta * COLOR_LERP_PER_SECOND);
    this.tipMaterial.color.lerp(statusColor(this.status), factor);

    const targetOpacity = statusOpacity(this.status);
    for (const material of this.fadeMaterials) {
      material.opacity += (targetOpacity - material.opacity) * factor;
    }

    const t = elapsed + this.phase;
    const working = this.status === 'WORKING' && motionEnabled;
    if (working) {
      // 양팔이 번갈아 치는 타이핑 + 팁 맥동. 멀리서도 "일하는 중"이 움직임으로 읽힌다.
      this.leftArm.rotation.x = ARM_REACH_TILT + Math.sin(t * TYPING_SPEED) * TYPING_AMPLITUDE;
      this.rightArm.rotation.x =
        ARM_REACH_TILT + Math.sin(t * TYPING_SPEED + Math.PI) * TYPING_AMPLITUDE;
      this.head.rotation.z = Math.sin(t * HEAD_SWAY_SPEED) * HEAD_SWAY_AMPLITUDE;
      const pulse = 1 + Math.sin(t * 4) * TIP_PULSE_SCALE;
      this.tip.scale.setScalar(pulse);
    } else if (motionEnabled) {
      this.leftArm.rotation.x = ARM_REACH_TILT;
      this.rightArm.rotation.x = ARM_REACH_TILT;
      this.head.rotation.z = 0;
      this.tip.scale.setScalar(1);
    }

    // 눈 깜빡임. 일할 때만은 아니다 — 앉아 있으면 생명체처럼 보여야 한다.
    if (motionEnabled) {
      const blinking = t % BLINK_CYCLE < BLINK_LENGTH;
      for (const eye of this.eyes) eye.scale.y = blinking ? 0.15 : 1;
    }
  }

  dispose(): void {
    this.object.traverse((child) => {
      if (child instanceof Mesh) {
        child.geometry.dispose();
      }
    });
    for (const material of this.fadeMaterials) material.dispose();
  }

  get pickables(): readonly Object3D[] {
    return this.object.children;
  }

  private applyOpacity(opacity: number): void {
    for (const material of this.fadeMaterials) material.opacity = opacity;
  }
}
