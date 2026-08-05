/**
 * 사무실 소품 — 데이터와 무관한 정적 장식 모음.
 *
 * 디오라마(축소 모형) 컨셉의 실질적인 재료다. 식물·책장·창문 같은 소품이 "방처럼"
 * 보이게 하는 전부이고, 여기 있는 건 전부 순수 장식이라 지우거나 바꿔도 도메인에
 * 영향이 없다. 배치 좌표는 직원 책상(DB 소유)과 달리 화면 전용이라 여기 상수로 둔다.
 *
 * 텍스처는 파일을 추가하는 대신 canvas로 그린다 — 나뭇결·하늘·차트 정도는 코드로
 * 그리는 게 에셋 관리보다 가볍고, 빌드 산출물도 늘지 않는다.
 */

import {
  BoxGeometry,
  CanvasTexture,
  CircleGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
  RepeatWrapping,
  SphereGeometry,
  SRGBColorSpace,
  type Object3D,
  type Texture,
} from 'three';

/** 방 치수. 직원 5명의 책상 열(x -4..4)보다 넉넉하게 잡는다. */
export const ROOM = {
  width: 16,
  depth: 11,
  wallHeight: 3.4,
  wallThickness: 0.2,
} as const;

const WALL_COLOR = 0xf3efe7;
const BASEBOARD_COLOR = 0xe2dcd0;

function canvasTexture(size: number, draw: (ctx: CanvasRenderingContext2D) => void): Texture {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (ctx !== null) draw(ctx);
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}

/** 나무 바닥. 판자 결을 canvas로 그려 반복한다. */
export function createFloor(): Object3D {
  const grain = canvasTexture(512, (ctx) => {
    ctx.fillStyle = '#dfc39c';
    ctx.fillRect(0, 0, 512, 512);
    const rowHeight = 64;
    for (let row = 0; row < 512 / rowHeight; row += 1) {
      // 판자마다 밝기를 조금씩 다르게 — 같은 색 반복이면 카펫처럼 보인다.
      const lightness = 72 + ((row * 37) % 5) * 2;
      ctx.fillStyle = `hsl(36, 38%, ${lightness}%)`;
      ctx.fillRect(0, row * rowHeight, 512, rowHeight - 2);
      // 판자 사이 틈과 세로 이음새.
      ctx.fillStyle = 'rgba(122, 92, 54, 0.35)';
      ctx.fillRect(0, (row + 1) * rowHeight - 2, 512, 2);
      const seam = (row * 173) % 512;
      ctx.fillRect(seam, row * rowHeight, 2, rowHeight - 2);
    }
  });
  grain.wrapS = RepeatWrapping;
  grain.wrapT = RepeatWrapping;
  grain.repeat.set(3, 2);

  const floor = new Mesh(
    new PlaneGeometry(ROOM.width, ROOM.depth),
    new MeshStandardMaterial({ map: grain, roughness: 0.85, metalness: 0 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  return floor;
}

/** 뒷벽 + 양 옆벽 + 걸레받이. 정면은 열어둔다(인형집 시점). */
export function createWalls(): Object3D {
  const group = new Group();
  const material = new MeshStandardMaterial({ color: WALL_COLOR, roughness: 0.95 });
  const { width, depth, wallHeight, wallThickness } = ROOM;

  const back = new Mesh(new BoxGeometry(width, wallHeight, wallThickness), material);
  back.position.set(0, wallHeight / 2, -depth / 2 + wallThickness / 2);

  group.add(back);
  for (const side of [-1, 1]) {
    const wall = new Mesh(new BoxGeometry(wallThickness, wallHeight, depth), material);
    wall.position.set(
      (side * (width - wallThickness)) / 2,
      wallHeight / 2,
      0,
    );
    group.add(wall);
  }

  // 걸레받이: 벽과 바닥이 만나는 선. 이 한 줄이 있으면 "벽을 세운 방"처럼 읽힌다.
  const baseboardMaterial = new MeshStandardMaterial({ color: BASEBOARD_COLOR, roughness: 0.9 });
  const backBase = new Mesh(new BoxGeometry(width, 0.14, 0.03), baseboardMaterial);
  backBase.position.set(0, 0.07, -depth / 2 + wallThickness + 0.015);
  group.add(backBase);
  for (const side of [-1, 1]) {
    const base = new Mesh(new BoxGeometry(0.03, 0.14, depth), baseboardMaterial);
    base.position.set((side * (width / 2 - wallThickness - 0.015)), 0.07, 0);
    group.add(base);
  }

  for (const child of group.children) child.receiveShadow = true;
  return group;
}

/** 뒷벽의 창문. 하늘은 canvas 그라데이션, 프레임은 흰 목재. */
export function createWindow(): Object3D {
  const group = new Group();
  const width = 4.6;
  const height = 2.1;
  const bottomY = 1.0;

  const sky = canvasTexture(512, (ctx) => {
    const gradient = ctx.createLinearGradient(0, 0, 0, 512);
    gradient.addColorStop(0, '#9fcfeb');
    gradient.addColorStop(0.62, '#d8ecf4');
    gradient.addColorStop(1, '#fce8cd');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 512, 512);
    // 해. bloom이 번지게 할 만큼 밝게.
    ctx.fillStyle = '#fff6dd';
    ctx.beginPath();
    ctx.arc(370, 120, 52, 0, Math.PI * 2);
    ctx.fill();
    // 구름 두 덩이.
    ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
    for (const [x, y, r] of [
      [140, 150, 34],
      [185, 165, 26],
      [330, 260, 30],
      [372, 272, 22],
    ] as const) {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  });
  const glass = new Mesh(
    new PlaneGeometry(width, height),
    new MeshStandardMaterial({ map: sky, roughness: 0.4, emissive: 0xffffff, emissiveMap: sky, emissiveIntensity: 0.55 }),
  );

  const frameMaterial = new MeshStandardMaterial({ color: 0xfaf8f4, roughness: 0.6 });
  const bar = 0.09;
  const horizontal = new BoxGeometry(width + bar * 2, bar, bar);
  const vertical = new BoxGeometry(bar, height + bar * 2, bar);
  const top = new Mesh(horizontal, frameMaterial);
  top.position.y = height / 2 + bar / 2;
  const bottom = new Mesh(horizontal, frameMaterial);
  bottom.position.y = -height / 2 - bar / 2;
  const left = new Mesh(vertical, frameMaterial);
  left.position.x = -width / 2 - bar / 2;
  const right = new Mesh(vertical, frameMaterial);
  right.position.x = width / 2 + bar / 2;
  // 십자 창살.
  const mullionV = new Mesh(new BoxGeometry(bar * 0.7, height, bar * 0.7), frameMaterial);
  const mullionH = new Mesh(new BoxGeometry(width, bar * 0.7, bar * 0.7), frameMaterial);

  group.add(glass, top, bottom, left, right, mullionV, mullionH);
  group.position.set(-3.9, bottomY + height / 2, -ROOM.depth / 2 + ROOM.wallThickness + 0.002);
  return group;
}

/** 화이트보드. 차트 낙서가 "일하는 사무실" 느낌을 낸다. */
export function createWhiteboard(): Object3D {
  const group = new Group();
  const width = 2.7;
  const height = 1.5;

  const boardTexture = canvasTexture(512, (ctx) => {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, 512, 512);
    // 옅은 모눈.
    ctx.strokeStyle = '#eef1f4';
    ctx.lineWidth = 1;
    for (let i = 64; i < 512; i += 64) {
      ctx.beginPath();
      ctx.moveTo(i, 0);
      ctx.lineTo(i, 512);
      ctx.moveTo(0, i);
      ctx.lineTo(512, i);
      ctx.stroke();
    }
    // 제목 낙서 두 줄.
    ctx.strokeStyle = '#8b96a3';
    ctx.lineWidth = 6;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(40, 56);
    ctx.lineTo(210, 56);
    ctx.moveTo(40, 84);
    ctx.lineTo(150, 84);
    ctx.stroke();
    // 막대 차트.
    const bars: ReadonlyArray<readonly [number, number, string]> = [
      [60, 150, '#c9d8e8'],
      [130, 210, '#c9d8e8'],
      [200, 180, '#f5c98f'],
      [270, 260, '#a8d5ba'],
    ];
    for (const [x, barHeight, color] of bars) {
      ctx.fillStyle = color;
      ctx.fillRect(x, 430 - barHeight, 46, barHeight);
    }
    // 우상향 꺾은선.
    ctx.strokeStyle = '#4f46e5';
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.moveTo(50, 380);
    ctx.lineTo(150, 320);
    ctx.lineTo(250, 345);
    ctx.lineTo(350, 240);
    ctx.lineTo(455, 180);
    ctx.stroke();
    ctx.fillStyle = '#4f46e5';
    for (const [x, y] of [
      [50, 380],
      [150, 320],
      [250, 345],
      [350, 240],
      [455, 180],
    ] as const) {
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fill();
    }
  });

  const board = new Mesh(
    new PlaneGeometry(width, height),
    new MeshStandardMaterial({ map: boardTexture, roughness: 0.5 }),
  );
  const frame = new Mesh(
    new BoxGeometry(width + 0.1, height + 0.1, 0.04),
    new MeshStandardMaterial({ color: 0xd8d2c6, roughness: 0.7 }),
  );
  frame.position.z = -0.021;
  // 펜 트레이.
  const tray = new Mesh(
    new BoxGeometry(width * 0.5, 0.03, 0.08),
    new MeshStandardMaterial({ color: 0xc9c2b4, roughness: 0.7 }),
  );
  tray.position.set(0, -height / 2 - 0.08, 0.04);

  group.add(frame, board, tray);
  group.position.set(2.7, 1.75, -ROOM.depth / 2 + ROOM.wallThickness + 0.03);
  return group;
}

/** 벽시계. 바늘은 10시 10분 — 시계 디스플레이의 관례다. */
export function createClock(): Object3D {
  const group = new Group();
  const face = new Mesh(
    new CylinderGeometry(0.26, 0.26, 0.04, 32),
    new MeshStandardMaterial({ color: 0xffffff, roughness: 0.5 }),
  );
  face.rotation.x = Math.PI / 2;
  const rim = new Mesh(
    new CylinderGeometry(0.28, 0.28, 0.03, 32),
    new MeshStandardMaterial({ color: 0x8b8578, roughness: 0.6 }),
  );
  rim.rotation.x = Math.PI / 2;
  rim.position.z = -0.008;

  const handMaterial = new MeshStandardMaterial({ color: 0x3a362f, roughness: 0.5 });
  const hourHand = new Mesh(new BoxGeometry(0.03, 0.13, 0.01), handMaterial);
  hourHand.position.set(0.03, 0.045, 0.025);
  hourHand.rotation.z = -0.9;
  const minuteHand = new Mesh(new BoxGeometry(0.02, 0.2, 0.01), handMaterial);
  minuteHand.position.set(-0.035, 0.07, 0.025);
  minuteHand.rotation.z = 0.35;

  group.add(rim, face, hourHand, minuteHand);
  group.position.set(0.35, 2.6, -ROOM.depth / 2 + ROOM.wallThickness + 0.05);
  return group;
}

/** 책상 열 아래 깔리는 러그. 두 겹 원을 타원으로 늘린다. */
export function createRug(): Object3D {
  const group = new Group();
  const outer = new Mesh(
    new CircleGeometry(1, 48),
    new MeshStandardMaterial({ color: 0xb9cdb8, roughness: 1 }),
  );
  outer.scale.set(5.9, 2.1, 1);
  outer.rotation.x = -Math.PI / 2;
  const inner = new Mesh(
    new CircleGeometry(1, 48),
    new MeshStandardMaterial({ color: 0xccdccf, roughness: 1 }),
  );
  inner.scale.set(5.45, 1.75, 1);
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = 0.004;
  outer.receiveShadow = true;
  inner.receiveShadow = true;
  group.add(outer, inner);
  group.position.set(0, 0.012, 0.15);
  return group;
}

/** 화분 식물. 줄기 + 잎 구체 몇 개의 조합이 로우폴리 식물로 읽힌다. */
export function createPlant(scale = 1): Object3D {
  const group = new Group();
  const pot = new Mesh(
    new CylinderGeometry(0.17, 0.13, 0.26, 20),
    new MeshStandardMaterial({ color: 0xc07a58, roughness: 0.9 }),
  );
  pot.position.y = 0.13;
  const trunk = new Mesh(
    new CylinderGeometry(0.025, 0.035, 0.5, 8),
    new MeshStandardMaterial({ color: 0x8a6a4a, roughness: 1 }),
  );
  trunk.position.y = 0.48;
  group.add(pot, trunk);

  const leafMaterial = new MeshStandardMaterial({ color: 0x6d9c6f, roughness: 1 });
  const leafDark = new MeshStandardMaterial({ color: 0x5b8a5e, roughness: 1 });
  const leaves: ReadonlyArray<readonly [number, number, number, number, MeshStandardMaterial]> = [
    [0, 0.86, 0, 0.24, leafMaterial],
    [0.16, 0.72, 0.06, 0.17, leafDark],
    [-0.15, 0.75, -0.05, 0.18, leafMaterial],
    [0.02, 0.68, 0.16, 0.14, leafDark],
  ];
  for (const [x, y, z, radius, material] of leaves) {
    const leaf = new Mesh(new SphereGeometry(radius, 14, 12), material);
    leaf.position.set(x, y, z);
    leaf.castShadow = true;
    group.add(leaf);
  }
  pot.castShadow = true;
  group.scale.setScalar(scale);
  return group;
}

/** 책장. 책 등 색은 고정 배열 — Math.random을 쓰면 새로고침 때마다 방이 바뀐다. */
export function createBookshelf(): Object3D {
  const group = new Group();
  const width = 1.7;
  const height = 1.9;
  const depth = 0.3;
  const shelfCount = 4;

  const frameMaterial = new MeshStandardMaterial({ color: 0xe8e0d2, roughness: 0.8 });
  for (const side of [-1, 1]) {
    const panel = new Mesh(new BoxGeometry(0.05, height, depth), frameMaterial);
    panel.position.set((side * width) / 2, height / 2, 0);
    panel.castShadow = true;
    group.add(panel);
  }
  const shelfHeight = height / shelfCount;
  for (let i = 0; i <= shelfCount; i += 1) {
    const shelf = new Mesh(new BoxGeometry(width, 0.04, depth), frameMaterial);
    shelf.position.set(0, i * shelfHeight + 0.02, 0);
    group.add(shelf);
  }

  const SPINES = ['#c96f5a', '#7fa3c9', '#a8b98a', '#d9b36c', '#9a8ab8', '#c98aa5', '#7ab8b0'] as const;
  for (let row = 0; row < shelfCount; row += 1) {
    // 칸마다 책 수와 기울기를 다르게 — 빈틈이 있어야 진짜 책장처럼 보인다.
    let x = -width / 2 + 0.12;
    let spine = row * 3;
    while (x < width / 2 - 0.2) {
      const bookHeight = 0.24 + ((spine * 13) % 5) * 0.02;
      const bookWidth = 0.05 + ((spine * 7) % 3) * 0.012;
      const book = new Mesh(
        new BoxGeometry(bookWidth, bookHeight, depth * 0.72),
        new MeshStandardMaterial({
          color: SPINES[spine % SPINES.length] ?? SPINES[0],
          roughness: 0.85,
        }),
      );
      book.position.set(x, row * shelfHeight + 0.04 + bookHeight / 2, 0);
      if ((spine * 11) % 7 === 0) book.rotation.z = -0.08;
      book.castShadow = true;
      group.add(book);
      x += bookWidth + 0.015;
      spine += 1;
      if ((spine * 5) % 9 === 0) x += 0.09;
    }
  }
  return group;
}

/** 펜던트 조명. 전구만 emissive라 bloom이 여기서 번진다. */
export function createPendantLamp(): Object3D {
  const group = new Group();
  const cord = new Mesh(
    new CylinderGeometry(0.012, 0.012, 0.7, 6),
    new MeshStandardMaterial({ color: 0x4a463e, roughness: 0.7 }),
  );
  cord.position.y = -0.35;
  const shade = new Mesh(
    new CylinderGeometry(0.03, 0.22, 0.18, 24, 1, true),
    new MeshStandardMaterial({ color: 0xf5f1e8, roughness: 0.5, side: 2 }),
  );
  shade.position.y = -0.78;
  const bulb = new Mesh(
    new SphereGeometry(0.05, 12, 10),
    new MeshStandardMaterial({
      color: 0xfff2d8,
      emissive: 0xffd9a0,
      emissiveIntensity: 2.6,
    }),
  );
  bulb.position.y = -0.85;
  group.add(cord, shade, bulb);
  return group;
}
