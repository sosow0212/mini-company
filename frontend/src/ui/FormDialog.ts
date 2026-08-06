/**
 * 폼 다이얼로그 공통 골격.
 *
 * 네이티브 `<dialog>`를 쓴다 — ESC 닫기, 포커스 트랩, 배경 비활성화(inert)가 브라우저
 * 기본 동작으로 따라온다. 직접 만들면 이 셋 중 하나는 반드시 빠뜨린다.
 *
 * 제출 중에는 버튼을 잠근다. 두 번 눌러 직원이 둘 생기는 것보다 잠깐 못 누르는 편이 낫다.
 */

import { ApiError } from '../api/client';

export abstract class FormDialog<T> {
  protected readonly dialog: HTMLDialogElement;
  private readonly form: HTMLFormElement;
  private readonly errorSlot: HTMLParagraphElement;
  private readonly submitButton: HTMLButtonElement;

  constructor(title: string, submitLabel: string) {
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'dialog';
    this.dialog.innerHTML = `
      <form method="dialog" class="dialog__form">
        <header class="dialog__head">
          <h2 class="dialog__title">${title}</h2>
          <button type="button" class="icon-button" data-cancel aria-label="닫기">✕</button>
        </header>
        <div class="dialog__body"></div>
        <p class="dialog__error" role="alert" hidden></p>
        <footer class="dialog__foot">
          <button type="button" class="button button--ghost" data-cancel>취소</button>
          <button type="submit" class="button button--primary">${submitLabel}</button>
        </footer>
      </form>
    `;
    document.body.append(this.dialog);

    this.form = this.dialog.querySelector('form') as HTMLFormElement;
    this.errorSlot = this.dialog.querySelector('.dialog__error') as HTMLParagraphElement;
    this.submitButton = this.dialog.querySelector('[type="submit"]') as HTMLButtonElement;

    for (const button of this.dialog.querySelectorAll('[data-cancel]')) {
      button.addEventListener('click', () => {
        this.dialog.close();
      });
    }
    // method="dialog"라 기본 동작은 즉시 닫기다. 서버 응답을 기다려야 하므로 막는다.
    this.form.addEventListener('submit', (event) => {
      event.preventDefault();
      void this.handleSubmit();
    });
  }

  protected get body(): HTMLElement {
    return this.dialog.querySelector('.dialog__body') as HTMLElement;
  }

  /** 폼 값을 읽어 서버에 보낸다. 성공하면 다이얼로그가 닫힌다. */
  protected abstract submit(): Promise<T>;

  protected open(): void {
    this.errorSlot.hidden = true;
    this.dialog.showModal();
    const first = this.dialog.querySelector<HTMLElement>('input, select');
    first?.focus();
  }

  private async handleSubmit(): Promise<void> {
    this.submitButton.disabled = true;
    this.errorSlot.hidden = true;
    try {
      const result = await this.submit();
      this.dialog.close();
      this.onDone(result);
    } catch (error: unknown) {
      // 서버가 준 문장을 그대로 보여준다. "직원이 이미 다른 작업을 수행 중입니다"처럼
      // 사용자가 다음에 무엇을 할지 알 수 있는 문장이라 다시 쓸 이유가 없다.
      this.errorSlot.textContent =
        error instanceof ApiError ? error.detail : '요청을 처리하지 못했습니다.';
      this.errorSlot.hidden = false;
    } finally {
      this.submitButton.disabled = false;
    }
  }

  /** 성공 후 호출. 목록 새로고침 같은 후처리를 붙인다. */
  protected onDone: (result: T) => void = () => {};

  setOnDone(handler: (result: T) => void): void {
    this.onDone = handler;
  }
}
