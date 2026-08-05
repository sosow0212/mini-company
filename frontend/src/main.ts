/**
 * 조립 지점.
 *
 * 데이터 흐름(§12):
 *   진입 → snapshot → store → 씬 구성
 *        → WS 연결 → 이벤트 → store 패치 → 다음 프레임에 반영
 *        → 끊김 → 지수 백오프 재연결 → **성공 시 snapshot 재조회**
 *
 * 마지막 줄이 핵심이다. 재연결 후 이벤트만 이어받으면 끊긴 동안의 변경이 영구 유실된다.
 */

import './styles/tokens.css';
import './styles/global.css';

import { fetchSnapshot } from './api/client';
import { connectOfficeSocket } from './api/socket';
import { OfficeScene } from './scene/OfficeScene';
import { OfficeStore } from './state/officeStore';
import { EmployeePanel } from './ui/EmployeePanel';
import { LedgerPanel } from './ui/LedgerPanel';
import { NameTag } from './ui/NameTag';
import { SpeechBubble } from './ui/SpeechBubble';

const BUBBLE_SWEEP_MS = 1_000;

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`필수 요소가 없다: #${id}`);
  return element;
}

async function main(): Promise<void> {
  const store = new OfficeStore();
  const ledgerPanel = new LedgerPanel(requireElement('ledger-panel'));
  const employeePanel = new EmployeePanel(requireElement('employee-panel'));
  const connectionBadge = requireElement('connection-badge');

  const scene = new OfficeScene(requireElement('scene-host'), (employeeId) => {
    if (employeeId === null) {
      employeePanel.close();
      return;
    }
    const view = store.findEmployee(employeeId);
    if (view !== undefined) void employeePanel.open(view.employee);
  });

  const bubbles = new Map<string, SpeechBubble>();
  const nameTags = new Map<string, NameTag>();

  store.subscribe(() => {
    const employees = store.listEmployees();
    scene.syncEmployees(employees.map((view) => view.employee));

    for (const view of employees) {
      const { id } = view.employee;

      // 네임태그는 상주한다. 아바타가 새로 생길 때 한 번만 붙이고 이후 상태만 갱신한다.
      let nameTag = nameTags.get(id);
      if (nameTag === undefined) {
        nameTag = new NameTag(view.employee);
        nameTags.set(id, nameTag);
        scene.attachLabel(id, nameTag.label);
      }
      nameTag.setStatus(view.employee.status);

      let bubble = bubbles.get(id);
      if (bubble === undefined) {
        bubble = new SpeechBubble();
        bubbles.set(id, bubble);
        scene.attachLabel(id, bubble.label);
      }
      const latest = view.recentActivities.at(0);
      if (latest !== undefined) {
        bubble.show(latest.message, latest.level, new Date(latest.occurredAt).getTime());
      }
    }

    ledgerPanel.render(store.ledger());
  });

  // 말풍선 만료는 store와 무관한 표시 관심사다. 별 타이머로 돌린다.
  window.setInterval(() => {
    const now = Date.now();
    for (const bubble of bubbles.values()) bubble.expireIfStale(now);
  }, BUBBLE_SWEEP_MS);

  store.replaceWithSnapshot(await fetchSnapshot());
  scene.start();

  connectOfficeSocket({
    onEvent: (event) => store.apply(event),
    onReconnect: () => {
      // 끊긴 동안의 변경을 여기서 되찾는다.
      void fetchSnapshot().then((snapshot) => store.replaceWithSnapshot(snapshot));
    },
    onStatusChange: (connected) => {
      connectionBadge.dataset.state = connected ? 'live' : 'down';
      connectionBadge.textContent = connected ? 'LIVE' : '재연결 중';
    },
  });
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  requireElement('boot-error').textContent = `초기화 실패: ${message}`;
  requireElement('boot-error').hidden = false;
});
