/**
 * 씬·카메라·렌더러·루프. 3D만 담당하고 DOM 패널은 모른다.
 *
 * 조명은 "밝은 실내"가 컨셉이다. 창문 쪽 역광 대신 카메라 쪽 소프트박스 조명을 쓴다 —
 * 벽이 주광을 가려버리는 역광을 피하고, 디오라마 전체가 고르게 읽히는 쪽이 관제에 낫다.
 * bloom(UnrealBloomPass)은 남기되 임계값을 1.0으로 올려 emissive가 실제로 1을 넘는
 * 것(전구·Busylight·안테나 팁)만 번지게 한다. 밝은 씬에서 임계값이 낮으면 흰 벽까지
 * 번져서 화면이 씻긴다.
 *
 * 말풍선·네임태그는 WebGL 텍스처가 아니라 CSS2DRenderer로 띄운다 — 한글 폰트와 줄바꿈이
 * 공짜다(§12). 카메라은 고정 아이소메트릭이다. 관제 화면은 매번 같은 구도로 보여야
 * 상태 차이가 눈에 들어온다.
 */

import {
  ACESFilmicToneMapping,
  Clock,
  Color,
  DirectionalLight,
  HemisphereLight,
  PerspectiveCamera,
  PointLight,
  Raycaster,
  Scene,
  Vector2,
  WebGLRenderer,
} from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import type { Employee } from '../api/types';
import { EmployeeAvatar } from './EmployeeAvatar';
import { createRoom, Workstation } from './OfficeLayout';

const CAMERA_POSITION = { x: 0, y: 7.6, z: 12.2 } as const;
const CAMERA_TARGET = { x: 0, y: 0.95, z: -0.3 } as const;

/**
 * 직원이 늘면 카메라가 물러난다.
 *
 * 고정 좌표는 시드 5명(한 줄)에 맞춰져 있었다. 채용해서 뒷줄이 생기면 그 직원들은
 * 화면 위로 밀려 이름표만 보이고 아바타는 잘린다 — "채용했는데 안 보인다"가 된다.
 *
 * 책상 좌표(서버가 정한다)의 실제 퍼짐을 재서 거리를 정한다. 인원수로 계산하면
 * 배치 규칙이 바뀔 때마다 여기도 같이 고쳐야 한다.
 */
// 물러나는 양을 좁게 잡는다. 방보다 넓게 잡으면 벽 바깥 여백이 화면을 먹고
// 사무실이 작은 모형처럼 보인다 — 뒷줄이 화면에 들어오는 만큼만 뺀다.
const CAMERA_DEPTH_PULL = 0.08;
const CAMERA_WIDTH_PULL = 0.06;
const CAMERA_MAX_DISTANCE_SCALE = 1.35;
/** 기준 배치의 좌우 폭. 이보다 넓어질 때만 추가로 물러난다. */
const BASELINE_SPREAD_X = 4;

function framingFor(desks: readonly { x: number; z: number }[]): {
  position: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
} {
  if (desks.length === 0) return { position: CAMERA_POSITION, target: CAMERA_TARGET };

  const spreadX = Math.max(...desks.map((desk) => Math.abs(desk.x)));
  const depth = Math.max(...desks.map((desk) => -desk.z), 0);
  const scale = Math.min(
    1 + depth * CAMERA_DEPTH_PULL + Math.max(spreadX - BASELINE_SPREAD_X, 0) * CAMERA_WIDTH_PULL,
    CAMERA_MAX_DISTANCE_SCALE,
  );
  return {
    position: {
      x: CAMERA_POSITION.x,
      y: CAMERA_POSITION.y * scale,
      z: CAMERA_POSITION.z * scale,
    },
    // 뒷줄이 생기면 시선도 안쪽으로 옮긴다. 안 그러면 앞줄만 화면 중앙에 온다.
    target: { ...CAMERA_TARGET, z: CAMERA_TARGET.z - depth / 2 },
  };
}

/** 페이지 배경(--surface-void)과 이어지는 따뜻한 종이색. */
const BACKGROUND = 0xe6e1d7;

const BLOOM_STRENGTH = 0.5;
const BLOOM_RADIUS = 0.55;
/** 임계값 1.0: 전구·상태등처럼 emissive가 1을 넘는 것만 번진다. */
const BLOOM_THRESHOLD = 1.0;

export class OfficeScene {
  private readonly scene = new Scene();
  private readonly camera: PerspectiveCamera;
  private readonly renderer: WebGLRenderer;
  private readonly composer: EffectComposer;
  private readonly labelRenderer: CSS2DRenderer;
  private readonly clock = new Clock();
  private readonly raycaster = new Raycaster();
  private readonly avatars = new Map<string, EmployeeAvatar>();
  private readonly workstations = new Map<string, Workstation>();
  private frame = 0;
  private motionEnabled: boolean;

  constructor(
    private readonly host: HTMLElement,
    private readonly onPickEmployee: (employeeId: string | null) => void,
  ) {
    const { clientWidth: width, clientHeight: height } = host;

    this.scene.background = new Color(BACKGROUND);

    this.camera = new PerspectiveCamera(36, width / height, 0.1, 100);
    this.camera.position.set(CAMERA_POSITION.x, CAMERA_POSITION.y, CAMERA_POSITION.z);
    this.camera.lookAt(CAMERA_TARGET.x, CAMERA_TARGET.y, CAMERA_TARGET.z);

    this.renderer = new WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(width, height);
    this.renderer.shadowMap.enabled = true;
    // 톤매핑이 없으면 전구 주변이 흰색으로 타버려 상태색을 잃는다.
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    host.appendChild(this.renderer.domElement);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.composer.addPass(
      new UnrealBloomPass(new Vector2(width, height), BLOOM_STRENGTH, BLOOM_RADIUS, BLOOM_THRESHOLD),
    );
    this.composer.addPass(new OutputPass());

    // DOM 라벨은 별 레이어로 겹친다. pointer-events는 CSS에서 라벨에만 되살린다.
    this.labelRenderer = new CSS2DRenderer();
    this.labelRenderer.setSize(width, height);
    this.labelRenderer.domElement.className = 'label-layer';
    host.appendChild(this.labelRenderer.domElement);

    this.scene.add(createRoom());

    // 하늘(차가운 반사)과 바닥(나무의 따뜻한 반사)의 양방향 환경광.
    this.scene.add(new HemisphereLight(0xdfeaf2, 0xe8d5b8, 1.0));

    // 카메라 오른쪽 위의 주광. 그림자가 뒤로 길게 깔려 사물이 바닥에 붙어 보인다.
    const key = new DirectionalLight(0xfff2e0, 1.6);
    key.position.set(5, 10, 8);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -11;
    key.shadow.camera.right = 11;
    key.shadow.camera.top = 11;
    key.shadow.camera.bottom = -11;
    key.shadow.camera.far = 32;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.02;
    this.scene.add(key);

    // 펜던트 조명 자리의 따뜻한 점광. 책상 열에 온기를 더한다.
    const warm = new PointLight(0xffe0b3, 14, 16, 1.8);
    warm.position.set(0, 2.5, 0.5);
    this.scene.add(warm);

    // prefers-reduced-motion을 존중한다. 값이 바뀌면 즉시 반영한다.
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    this.motionEnabled = !query.matches;
    query.addEventListener('change', (event) => {
      this.motionEnabled = !event.matches;
    });

    this.renderer.domElement.addEventListener('pointerdown', this.handlePointerDown);
    window.addEventListener('resize', this.handleResize);
  }

  /** 스냅샷의 직원 목록에 씬을 맞춘다. 추가·삭제·상태 갱신을 모두 처리한다. */
  syncEmployees(employees: readonly Employee[]): void {
    const seen = new Set<string>();
    this.fitCamera(employees.map((employee) => employee.desk));

    for (const employee of employees) {
      seen.add(employee.id);
      const existing = this.avatars.get(employee.id);
      if (existing === undefined) {
        const avatar = new EmployeeAvatar(employee);
        this.avatars.set(employee.id, avatar);
        this.scene.add(avatar.object);

        const workstation = new Workstation(employee.desk, employee.role);
        workstation.setStatus(employee.status);
        this.workstations.set(employee.id, workstation);
        this.scene.add(workstation.object);
      } else {
        existing.setStatus(employee.status);
        this.workstations.get(employee.id)?.setStatus(employee.status);
      }
    }

    for (const [employeeId, avatar] of this.avatars) {
      if (seen.has(employeeId)) continue;
      this.scene.remove(avatar.object);
      avatar.dispose();
      this.avatars.delete(employeeId);
      const workstation = this.workstations.get(employeeId);
      if (workstation !== undefined) {
        this.scene.remove(workstation.object);
        workstation.dispose();
        this.workstations.delete(employeeId);
      }
    }
  }

  /** 책상이 전부 화면에 들어오도록 카메라를 옮긴다. */
  private fitCamera(desks: readonly { x: number; z: number }[]): void {
    const { position, target } = framingFor(desks);
    this.camera.position.set(position.x, position.y, position.z);
    this.camera.lookAt(target.x, target.y, target.z);
  }

  attachLabel(employeeId: string, label: CSS2DObject): void {
    this.avatars.get(employeeId)?.object.add(label);
  }

  start(): void {
    const render = (): void => {
      this.frame = requestAnimationFrame(render);
      const delta = this.clock.getDelta();
      const elapsed = this.clock.elapsedTime;
      for (const avatar of this.avatars.values()) {
        avatar.update(delta, elapsed, this.motionEnabled);
      }
      // renderer.render가 아니라 composer.render다. bloom 패스를 거쳐야 한다.
      this.composer.render();
      this.labelRenderer.render(this.scene, this.camera);
    };
    render();
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    window.removeEventListener('resize', this.handleResize);
    this.renderer.domElement.removeEventListener('pointerdown', this.handlePointerDown);
    for (const avatar of this.avatars.values()) avatar.dispose();
    for (const workstation of this.workstations.values()) workstation.dispose();
    this.composer.dispose();
    this.renderer.dispose();
  }

  private readonly handleResize = (): void => {
    const { clientWidth: width, clientHeight: height } = this.host;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    this.composer.setSize(width, height);
    this.labelRenderer.setSize(width, height);
  };

  private readonly handlePointerDown = (event: PointerEvent): void => {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(pointer, this.camera);

    const targets = [...this.avatars.values()].flatMap((avatar) => [...avatar.pickables]);
    const hit = this.raycaster.intersectObjects(targets, false).at(0);
    if (hit === undefined) {
      this.onPickEmployee(null);
      return;
    }
    // 클릭된 건 자식 메시다. 직원 id는 부모 그룹이 들고 있다.
    const employeeId = hit.object.parent?.userData.employeeId;
    this.onPickEmployee(typeof employeeId === 'string' ? employeeId : null);
  };
}
