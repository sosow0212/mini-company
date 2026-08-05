/**
 * 오피스 구조물 — 방(바닥·벽·소품)과 직원 워크스테이션(책상·의자·모니터·Busylight).
 *
 * 책상 좌표는 여기서 만들지 않는다. **DB의 `employee.desk`가 배치의 주인**이고,
 * 씬은 그 값을 읽어 놓기만 한다. 프론트가 좌표를 계산하면 시드와 화면이 갈라진다.
 *
 * 워크스테이션의 상태 신호는 **Busylight**(책상 위 상태등)다. 실제 사무실에서 쓰는
 * 물건이라 장식이 아니라 신호 체계로 읽히고, 칸막이 너머로도 보이는 게 강점이다.
 * 의자·모니터 스티커는 직무색 — 상태(변한다)와 정체성(변하지 않는다)을 분리한다.
 */

import {
  BoxGeometry,
  CircleGeometry,
  Color,
  CylinderGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  SphereGeometry,
  type Object3D,
} from 'three';
import type { Desk, EmployeeStatus, Role } from '../api/types';
import { roleColor, statusColor } from './palette';
import {
  createBookshelf,
  createClock,
  createFloor,
  createPendantLamp,
  createPlant,
  createRug,
  createWalls,
  createWhiteboard,
  createWindow,
  ROOM,
} from './props';

const DESK_WIDTH = 1.5;
const DESK_DEPTH = 0.8;
const DESK_THICKNESS = 0.05;
/* 실제 책상(0.72~0.75)보다 낮다. 디오라마는 캐릭터가 주연이라 책상이 얼굴을
   가리지 않는 비율을 택한다. */
const DESK_HEIGHT = 0.66;

/** 직원이 앉는 자리. 책상을 사이에 두고 카메라를 바라본다. */
export const SEAT_OFFSET_Z = -0.78;
export const DESK_SURFACE_Y = DESK_HEIGHT;

/** 방 전체를 조립한다. 소품 배치는 화면 전용이라 여기서 고정한다. */
export function createRoom(): Object3D {
  const room = new Group();
  room.add(createFloor(), createWalls(), createWindow(), createWhiteboard(), createClock(), createRug());

  const plantLeft = createPlant(1.15);
  plantLeft.position.set(-6.6, 0, -4.2);
  const plantRight = createPlant(0.85);
  plantRight.position.set(6.9, 0, -4.4);
  room.add(plantLeft, plantRight);

  const shelf = createBookshelf();
  shelf.position.set(5.75, 0, -ROOM.depth / 2 + ROOM.wallThickness + 0.16);
  room.add(shelf);

  for (const x of [-3, 0, 3]) {
    const lamp = createPendantLamp();
    lamp.position.set(x, ROOM.wallHeight, -0.2);
    room.add(lamp);
  }
  return room;
}

const DESK_TOP_COLOR = 0xf7f5f0;
const METAL_COLOR = 0xd9d4ca;
const DARK_PLASTIC = 0x3a4048;
/** 꺼진 상태등 색. OFFLINE 직원의 Busylight·로고는 색 대신 어두운 회색이 된다. */
const OFF_LIGHT_COLOR = new Color(0x8a9096);

export class Workstation {
  readonly object: Group;
  private readonly busyLightMaterial: MeshBasicMaterial;
  private readonly lidLogoMaterial: MeshBasicMaterial;

  constructor(desk: Desk, role: Role) {
    this.object = new Group();
    const identity = roleColor(role);

    // ── 책상: 흰 상판 + 양 끝 패널 다리 ──
    const top = new Mesh(
      new BoxGeometry(DESK_WIDTH, DESK_THICKNESS, DESK_DEPTH),
      new MeshStandardMaterial({ color: DESK_TOP_COLOR, roughness: 0.4 }),
    );
    top.position.y = DESK_HEIGHT - DESK_THICKNESS / 2;
    top.castShadow = true;
    top.receiveShadow = true;
    this.object.add(top);

    const legMaterial = new MeshStandardMaterial({ color: METAL_COLOR, roughness: 0.5, metalness: 0.4 });
    for (const side of [-1, 1]) {
      const leg = new Mesh(new BoxGeometry(0.05, DESK_HEIGHT - DESK_THICKNESS, DESK_DEPTH * 0.86), legMaterial);
      leg.position.set((side * (DESK_WIDTH - 0.12)) / 2, (DESK_HEIGHT - DESK_THICKNESS) / 2, 0);
      leg.castShadow = true;
      this.object.add(leg);
    }

    // ── 노트북: 모니터보다 위로 솟지 않아 얼굴을 가리지 않는다 ──
    const laptopBody = new MeshStandardMaterial({ color: 0xdfe3e6, roughness: 0.35, metalness: 0.5 });
    const laptopBase = new Mesh(new BoxGeometry(0.36, 0.018, 0.26), laptopBody);
    laptopBase.position.set(0, DESK_HEIGHT + 0.009, -0.26);
    const keyboard = new Mesh(
      new BoxGeometry(0.3, 0.005, 0.17),
      new MeshStandardMaterial({ color: 0xb9bfc5, roughness: 0.6 }),
    );
    keyboard.position.set(0, DESK_HEIGHT + 0.02, -0.24);

    const lid = new Mesh(new BoxGeometry(0.36, 0.24, 0.012), laptopBody);
    // 힌지는 베이스 뒤쪽. 상판이 카메라 쪽으로 살짝 젖혀져 있다.
    lid.position.set(0, DESK_HEIGHT + 0.135, -0.365);
    lid.rotation.x = 0.2;
    lid.castShadow = true;

    const screen = new Mesh(
      new BoxGeometry(0.32, 0.2, 0.004),
      new MeshStandardMaterial({ color: 0x22292f, roughness: 0.3 }),
    );
    screen.position.set(0, 0, -0.008);
    lid.add(screen);

    /*
     * 뚜껑 로고는 상태색으로 빛난다 — 카메라를 향하는 두 번째 상태등.
     * 조명을 받는 재질(Standard)을 쓰면 총 조도가 1을 넘어 ACES가 채도를 날려
     * 초록이 흰 점처럼 보인다. 작은 표시등은 unlit(Basic)으로 그려 조명과 무관하게
     * 정확한 상태색을 낸다 — 실제 LED가 멀리서 평면적으로 보이는 것과 같다.
     */
    this.lidLogoMaterial = new MeshBasicMaterial({ color: 0x8a9096 });
    const logo = new Mesh(new CircleGeometry(0.038, 20), this.lidLogoMaterial);
    logo.position.set(0, 0, 0.0075);
    lid.add(logo);
    this.object.add(laptopBase, keyboard, lid);

    const mug = new Mesh(
      new CylinderGeometry(0.045, 0.04, 0.09, 14),
      new MeshStandardMaterial({ color: identity, roughness: 0.5 }),
    );
    mug.position.set(0.52, DESK_HEIGHT + 0.045, -0.2);
    mug.castShadow = true;
    this.object.add(mug);

    // ── Busylight: 책상 앞쪽 모서리의 상태등. 받침대 위로 솟아 있어야
    //    카메라 높이에서 돔이 책상에 묻히지 않는다 ──
    const lightBase = new Mesh(
      new CylinderGeometry(0.05, 0.055, 0.016, 16),
      new MeshStandardMaterial({ color: DARK_PLASTIC, roughness: 0.5 }),
    );
    lightBase.position.set(-0.58, DESK_HEIGHT + 0.008, 0.3);
    const stalk = new Mesh(
      new CylinderGeometry(0.014, 0.014, 0.1, 8),
      new MeshStandardMaterial({ color: DARK_PLASTIC, roughness: 0.5 }),
    );
    stalk.position.set(-0.58, DESK_HEIGHT + 0.06, 0.3);
    this.busyLightMaterial = new MeshBasicMaterial({ color: 0x8a9096 });
    const dome = new Mesh(new SphereGeometry(0.068, 18, 12), this.busyLightMaterial);
    dome.position.set(-0.58, DESK_HEIGHT + 0.145, 0.3);
    this.object.add(lightBase, stalk, dome);

    // ── 의자: 시트·등받이는 직무색, 프레임은 무채색 ──
    const fabric = new MeshStandardMaterial({ color: identity, roughness: 0.9 });
    const frame = new MeshStandardMaterial({ color: 0x8b8578, roughness: 0.5, metalness: 0.5 });
    const base = new Mesh(new CylinderGeometry(0.24, 0.26, 0.035, 20), frame);
    base.position.set(0, 0.018, SEAT_OFFSET_Z);
    const pole = new Mesh(new CylinderGeometry(0.03, 0.03, 0.4, 10), frame);
    pole.position.set(0, 0.22, SEAT_OFFSET_Z);
    const seat = new Mesh(new CylinderGeometry(0.24, 0.24, 0.06, 20), fabric);
    seat.position.set(0, 0.42, SEAT_OFFSET_Z);
    seat.castShadow = true;
    const backrest = new Mesh(new BoxGeometry(0.42, 0.44, 0.055), fabric);
    backrest.position.set(0, 0.76, SEAT_OFFSET_Z - 0.2);
    backrest.rotation.x = 0.08;
    backrest.castShadow = true;
    this.object.add(base, pole, seat, backrest);

    this.object.position.set(desk.x, desk.y, desk.z);
  }

  setStatus(status: EmployeeStatus): void {
    const color = status === 'OFFLINE' ? OFF_LIGHT_COLOR : statusColor(status);
    for (const material of [this.busyLightMaterial, this.lidLogoMaterial]) {
      material.color.copy(color);
    }
  }

  dispose(): void {
    this.object.traverse((child) => {
      if (child instanceof Mesh) {
        child.geometry.dispose();
        const material = child.material as MeshStandardMaterial | MeshStandardMaterial[];
        for (const item of Array.isArray(material) ? material : [material]) item.dispose();
      }
    });
  }
}
