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
import './styles/controls.css';

import { fetchSnapshot } from './api/client';
import { connectOfficeSocket } from './api/socket';
import { OfficeScene } from './scene/OfficeScene';
import { OfficeStore } from './state/officeStore';
import { AssignDialog } from './ui/AssignDialog';
import { EditDialog } from './ui/EditDialog';
import { EmployeePanel } from './ui/EmployeePanel';
import { HireDialog } from './ui/HireDialog';
import { LedgerPanel } from './ui/LedgerPanel';
import { NameTag } from './ui/NameTag';
import { SpeechBubble } from './ui/SpeechBubble';
import { TaskPanel } from './ui/TaskPanel';

const BUBBLE_SWEEP_MS = 1_000;

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`필수 요소가 없다: #${id}`);
  return element;
}

async function main(): Promise<void> {
  const store = new OfficeStore();
  const ledgerPanel = new LedgerPanel(requireElement('ledger-panel'));
  const taskPanel = new TaskPanel(requireElement('task-panel'));
  const connectionBadge = requireElement('connection-badge');

  /**
   * 직원 목록이 바뀌면 스냅샷을 다시 받는다.
   *
   * 채용·해고에는 전용 WS 이벤트가 없다(상태 변경 이벤트는 이미 있는 직원에 대한 것이다).
   * 이벤트를 새로 만드는 대신 스냅샷 재조회로 맞춘다 — 사람이 누르는 빈도라 비용이 없고,
   * 재연결 복구가 쓰는 경로와 같아서 갈라질 코드가 없다(§12).
   */
  const reloadRoster = async (): Promise<void> => {
    store.replaceWithSnapshot(await fetchSnapshot());
    await taskPanel.refresh();
  };

  // 직원이 하나도 없으면 3D 씬이 텅 빈 방이라 무엇을 해야 할지 알 수 없다.
  const emptyState = requireElement('empty-state');

  const hireDialog = new HireDialog();
  const assignDialog = new AssignDialog();
  const editDialog = new EditDialog();
  hireDialog.setOnDone(() => void reloadRoster());
  editDialog.setOnDone(() => void reloadRoster());
  assignDialog.setOnDone(() => void taskPanel.refresh());

  const employeePanel = new EmployeePanel(requireElement('employee-panel'), {
    onAssign: (employee) => {
      assignDialog.show(employee);
    },
    onEdit: (employee) => {
      editDialog.show(employee);
    },
    onFired: () => void reloadRoster(),
  });

  requireElement('hire-button').addEventListener('click', () => {
    hireDialog.show();
  });

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
    taskPanel.setEmployees(employees.map((view) => view.employee));
    emptyState.hidden = employees.length > 0;

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
  void taskPanel.refresh();
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
