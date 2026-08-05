/**
 * 오피스 구조물 — 바닥, 그리드, 책상.
 *
 * 책상 좌표는 여기서 만들지 않는다. **DB의 `employee.desk`가 배치의 주인**이고,
 * 씬은 그 값을 읽어 놓기만 한다. 프론트가 좌표를 계산하면 시드와 화면이 갈라진다.
 *
 * 사물을 자세히 만드는 대신 **선과 빛**으로 공간을 만든다. 발광 그리드가 바닥의 깊이를,
 * 책상 엣지 라인이 사물의 경계를 알려준다 — 폴리곤을 늘리지 않고 밀도를 얻는 방법이다.
 */

import {
  BoxGeometry,
  EdgesGeometry,
  GridHelper,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
  type Object3D,
} from 'three';
import type { Desk } from '../api/types';

const DESK_WIDTH = 1.5;
const DESK_DEPTH = 0.72;
const DESK_THICKNESS = 0.05;
const DESK_HEIGHT = 0.64;
const FLOOR_SIZE = 26;
const GRID_DIVISIONS = 26;

export const DESK_SURFACE_Y = DESK_HEIGHT;

export function createFloor(): Object3D {
  const floor = new Mesh(
    new PlaneGeometry(FLOOR_SIZE, FLOOR_SIZE),
    // 약한 metalness로 조명을 살짝 되쏘게 한다. 완전 무광이면 공간이 종이처럼 보인다.
    new MeshStandardMaterial({ color: 0x0a0d16, roughness: 0.62, metalness: 0.35 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  return floor;
}

/** 발광 그리드. bloom이 이 선을 번지게 해서 바닥이 살아 있는 표면처럼 보인다. */
export function createGrid(): Object3D {
  const grid = new GridHelper(FLOOR_SIZE, GRID_DIVISIONS, 0x2f6d8f, 0x16283a);
  grid.position.y = 0.004;
  const material = grid.material as LineBasicMaterial | LineBasicMaterial[];
  for (const item of Array.isArray(material) ? material : [material]) {
    item.transparent = true;
    item.opacity = 0.5;
  }
  return grid;
}

export function createDesk(desk: Desk): Object3D {
  const group = new Group();

  const topGeometry = new BoxGeometry(DESK_WIDTH, DESK_THICKNESS, DESK_DEPTH);
  const top = new Mesh(
    topGeometry,
    new MeshStandardMaterial({
      color: 0x141b28,
      roughness: 0.35,
      metalness: 0.6,
      transparent: true,
      opacity: 0.92,
    }),
  );
  top.position.y = DESK_HEIGHT;
  top.castShadow = true;
  top.receiveShadow = true;

  // 엣지 라인이 유리판 테두리 역할을 한다. 면만으로는 어두운 배경에서 형태가 사라진다.
  const edges = new LineSegments(
    new EdgesGeometry(topGeometry),
    new LineBasicMaterial({ color: 0x3d8fb8, transparent: true, opacity: 0.75 }),
  );
  edges.position.y = DESK_HEIGHT;

  group.add(top, edges);

  for (const side of [-1, 1]) {
    const leg = new Mesh(
      new BoxGeometry(0.045, DESK_HEIGHT, 0.045),
      new MeshStandardMaterial({ color: 0x0e131d, roughness: 0.5, metalness: 0.7 }),
    );
    leg.position.set((side * (DESK_WIDTH - 0.16)) / 2, DESK_HEIGHT / 2, 0);
    group.add(leg);
  }

  group.position.set(desk.x, desk.y, desk.z);
  return group;
}
