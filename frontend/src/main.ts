/**
 * 조립 지점.
 *
 * 데이터 흐름(§12):
 *   진입 → snapshot → store → 씬 구성
 *        → WS 연결 → 이벤트 → store 패치 → 다음 프레임에 반영
 *        → 끊김 → 지수 백오프 재연결 → **성공 시 snapshot 재조회**
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
import { EmployeeDirectoryDialog } from './ui/EmployeeDirectoryDialog';
import { EmployeePanel } from './ui/EmployeePanel';
import { HireDialog } from './ui/HireDialog';
import { LedgerPanel } from './ui/LedgerPanel';
import { NameTag } from './ui/NameTag';
import { SpeechBubble } from './ui/SpeechBubble';
import { TaskPanel } from './ui/TaskPanel';
import { TaskResultDialog } from './ui/TaskResultDialog';

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

  const reloadRoster = async (): Promise<void> => {
    store.replaceWithSnapshot(await fetchSnapshot());
    await taskPanel.refresh();
  };

  const emptyState = requireElement('empty-state');

  const hireDialog = new HireDialog();
  const assignDialog = new AssignDialog();
  const editDialog = new EditDialog();
  const directoryDialog = new EmployeeDirectoryDialog();
  const taskResultDialog = new TaskResultDialog();

  hireDialog.setOnDone(() => void reloadRoster());
  editDialog.setOnDone(() => void reloadRoster());
  assignDialog.setOnDone(() => void taskPanel.refresh());

  taskPanel.setOnViewResult((task, employeeName) => {
    const employee = store.listEmployees().find((e) => e.employee.name === employeeName)?.employee;
    taskResultDialog.show(task, employeeName, employee?.llmProfile);
  });

  const employeePanel = new EmployeePanel(requireElement('employee-drawer'), {
    onAssign: (employee) => {
      assignDialog.show(employee);
    },
    onEdit: (employee) => {
      editDialog.show(employee);
    },
    onFired: () => void reloadRoster(),
    onViewResult: (task, employeeName, llmProfile) => {
      taskResultDialog.show(task, employeeName, llmProfile);
    },
  });

  directoryDialog.setOnSelectEmployee((employee) => {
    void employeePanel.open(employee);
  });
  directoryDialog.setOnHireClick(() => {
    hireDialog.show();
  });

  requireElement('hire-button').addEventListener('click', () => {
    hireDialog.show();
  });

  requireElement('directory-button').addEventListener('click', () => {
    directoryDialog.open();
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
    const employeeList = employees.map((view) => view.employee);

    scene.syncEmployees(employeeList);
    taskPanel.setEmployees(employeeList);
    directoryDialog.setEmployees(employeeList);

    emptyState.hidden = employees.length > 0;

    for (const view of employees) {
      const { id } = view.employee;

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
