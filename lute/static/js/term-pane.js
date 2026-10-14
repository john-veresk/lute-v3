"use strict";

/**
 * On narrow screens the term pane slides over the text.  An open pane
 * owns one history entry, so the system Back button closes it.
 */
class TermPane {
  constructor({pane, root, history, isCompact}) {
    this.pane = pane;
    this.root = root;
    this.history = history;
    this.isCompact = isCompact;
    this.requested = false;
    this.unwinding = false;
  }

  get isOpen() { return this.pane.classList.contains('open-dict'); }

  get ownsHistoryEntry() { return this.history.state?.luteTermPane === true; }

  /** Remember that the reader tapped text, so the next form load should open. */
  request() { this.requested = true; }

  openIfRequested() {
    const requested = this.requested;
    this.requested = false;
    return requested && this.open();
  }

  open() {
    if (!this.isCompact()) return false;
    this.unwinding = false;
    this.pane.classList.add('open-dict');
    this.root.classList.add('term-pane-open');
    if (!this.ownsHistoryEntry) this.history.pushState({luteTermPane: true}, '');
    return true;
  }

  hide() {
    this.pane.classList.remove('open-dict');
    this.root.classList.remove('term-pane-open');
  }

  close() {
    if (!this.isOpen) return;
    this.hide();
    this.stepBack();
  }

  /** Each step stays on the reading page: the current entry belongs to the pane. */
  stepBack() {
    this.unwinding = this.ownsHistoryEntry;
    if (this.unwinding) this.history.back();
  }

  onPopState() {
    this.unwinding = false;
    if (!this.ownsHistoryEntry) this.hide();
  }

  /**
   * Back can reload the term frame before the pane entry has actually gone.
   * Do not step back again: that next entry is often Review, when the book
   * was opened from there.
   */
  onFrameTraversed() {
    this.unwinding = false;
  }
}
