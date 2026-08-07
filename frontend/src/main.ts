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
import { KnowledgePanel } from './ui/KnowledgePanel';
import { LedgerPanel } from './ui/LedgerPanel';
import { NameTag } from './ui/NameTag';
import { ScheduleDialog } from './ui/ScheduleDialog';
import { SchedulePanel } from './ui/SchedulePanel';
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
  const schedulePanel = new SchedulePanel(requireElement('schedule-panel'));
  const knowledgePanel = new KnowledgePanel(requireElement('knowledge-panel'));
  const connectionBadge = requireElement('connection-badge');

  const reloadRoster = async (): Promise<void> => {
    store.replaceWithSnapshot(await fetchSnapshot());
    await taskPanel.refresh();
    await schedulePanel.refresh();
  };

  const emptyState = requireElement('empty-state');

  const hireDialog = new HireDialog();
  const assignDialog = new AssignDialog();
  const editDialog = new EditDialog();
  const directoryDialog = new EmployeeDirectoryDialog();
  const scheduleDialog = new ScheduleDialog();
  const taskResultDialog = new TaskResultDialog();

  hireDialog.setOnDone(() => void reloadRoster());
  editDialog.setOnDone(() => void reloadRoster());
  assignDialog.setOnDone(() => void taskPanel.refresh());
  scheduleDialog.setOnDone(() => void schedulePanel.refresh());
  schedulePanel.setOnAdd(() => {
    scheduleDialog.show(store.listEmployees().map((view) => view.employee));
  });

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

  // 탭 전환. 선택된 패널만 남기고 나머지는 hidden — 레일 높이를 넘지 않게 한다.
  const tabs = document.querySelectorAll<HTMLElement>('[data-tab]');
  const panels = document.querySelectorAll<HTMLElement>('[data-tabpanel]');
  for (const tab of tabs) {
    tab.addEventListener('click', () => {
      const selected = tab.dataset.tab;
      for (const other of tabs) {
        other.setAttribute('aria-selected', String(other.dataset.tab === selected));
      }
      for (const panel of panels) {
        panel.hidden = panel.dataset.tabpanel !== selected;
      }
    });
  }

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
    // 진행 중인 작업의 '지금 무슨 단계인가'는 store의 최근 활동에서 온다.
    taskPanel.setProgress(employees);
    schedulePanel.setEmployees(employeeList);
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
  void schedulePanel.refresh();
  void knowledgePanel.refresh();
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
