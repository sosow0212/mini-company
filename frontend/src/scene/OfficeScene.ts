/**
 * 씬·카메라·렌더러·루프. 3D만 담당하고 DOM 패널은 모른다.
 *
 * bloom(UnrealBloomPass)을 넣은 이유: 아바타의 상태 링과 바닥 그리드가 **번져야** 발광으로
 * 읽힌다. bloom 없이 emissive만 올리면 그냥 밝은 색면이고, 그게 "투박함"의 원인이다.
 * 대가는 번들 약 25kB와 후처리 1패스 — 3D 앱 예산(300kB gzip) 안에서 감당한다.
 *
 * 말풍선·네임태그는 WebGL 텍스처가 아니라 CSS2DRenderer로 띄운다 — 한글 폰트와 줄바꿈이
 * 공짜다(§12). 카메라는 고정 아이소메트릭이다. 관제 화면은 매번 같은 구도로 보여야
 * 상태 차이가 눈에 들어온다.
 */

import {
  ACESFilmicToneMapping,
  AmbientLight,
  Clock,
  Color,
  DirectionalLight,
  Fog,
  PerspectiveCamera,
  PointLight,
  Raycaster,
  Scene,
  Vector2,
  WebGLRenderer,
  type Object3D,
} from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import type { Employee } from '../api/types';
import { EmployeeAvatar } from './EmployeeAvatar';
import { createDesk, createFloor, createGrid } from './OfficeLayout';

const CAMERA_POSITION = { x: 0, y: 5.1, z: 8.4 } as const;
const CAMERA_TARGET_Y = 1.0;

const BACKGROUND = 0x070910;
/** 원경을 배경색으로 녹여 바닥 끝이 잘린 것처럼 보이지 않게 한다. */
const FOG_NEAR = 12;
const FOG_FAR = 30;

const BLOOM_STRENGTH = 0.62;
const BLOOM_RADIUS = 0.72;
/** 임계값을 높게 둬서 emissive한 것(링·코어·그리드)만 번지게 한다. */
const BLOOM_THRESHOLD = 0.42;

export class OfficeScene {
  private readonly scene = new Scene();
  private readonly camera: PerspectiveCamera;
  private readonly renderer: WebGLRenderer;
  private readonly composer: EffectComposer;
  private readonly labelRenderer: CSS2DRenderer;
  private readonly clock = new Clock();
  private readonly raycaster = new Raycaster();
  private readonly avatars = new Map<string, EmployeeAvatar>();
  private readonly desks = new Map<string, Object3D>();
  private frame = 0;
  private motionEnabled: boolean;

  constructor(
    private readonly host: HTMLElement,
    private readonly onPickEmployee: (employeeId: string | null) => void,
  ) {
    const { clientWidth: width, clientHeight: height } = host;

    this.scene.background = new Color(BACKGROUND);
    this.scene.fog = new Fog(BACKGROUND, FOG_NEAR, FOG_FAR);

    this.camera = new PerspectiveCamera(40, width / height, 0.1, 100);
    this.camera.position.set(CAMERA_POSITION.x, CAMERA_POSITION.y, CAMERA_POSITION.z);
    this.camera.lookAt(0, CAMERA_TARGET_Y, 0);

    this.renderer = new WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(width, height);
    this.renderer.shadowMap.enabled = true;
    // 톤매핑이 없으면 bloom이 흰색으로 타버려 상태색을 잃는다.
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
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

    this.scene.add(createFloor(), createGrid(), new AmbientLight(0x6f86b8, 0.85));

    // 위에서 내려오는 주광. 그림자로 아바타가 바닥에 붙어 있게 만든다.
    const key = new DirectionalLight(0xdce8ff, 1.15);
    key.position.set(3.5, 9, 5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.far = 24;
    this.scene.add(key);

    // 청록 림 라이트. 유리 재질의 엣지를 살려 형태가 배경에 묻히지 않게 한다.
    const rim = new PointLight(0x2f8fd0, 26, 20);
    rim.position.set(-5, 2.6, -4);
    this.scene.add(rim);

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

    for (const employee of employees) {
      seen.add(employee.id);
      const existing = this.avatars.get(employee.id);
      if (existing === undefined) {
        const avatar = new EmployeeAvatar(employee);
        this.avatars.set(employee.id, avatar);
        this.scene.add(avatar.object);

        const desk = createDesk(employee.desk);
        this.desks.set(employee.id, desk);
        this.scene.add(desk);
      } else {
        existing.setStatus(employee.status);
      }
    }

    for (const [employeeId, avatar] of this.avatars) {
      if (seen.has(employeeId)) continue;
      this.scene.remove(avatar.object);
      avatar.dispose();
      this.avatars.delete(employeeId);
      const desk = this.desks.get(employeeId);
      if (desk !== undefined) {
        this.scene.remove(desk);
        this.desks.delete(employeeId);
      }
    }
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
