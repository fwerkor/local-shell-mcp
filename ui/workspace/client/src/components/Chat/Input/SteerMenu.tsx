import { useEffect, useId, useSyncExternalStore } from 'react';
import * as Ariakit from '@ariakit/react';
import { ArrowUp, MoreHorizontal } from 'lucide-react';
import type { Ref } from 'react';
import { useShortcutAriaKey, useShortcutDisplay } from '~/hooks/useKeyboardShortcuts';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

/** Shared row/bubble affordances for the during-run surfaces: the in-flight
 *  steer bubbles (`InFlightSteers`) and the queued/failed rows
 *  (`PendingSteerChips`) offer the same actions, so they share one menu. */
export const ICON_BTN_CLASS =
  'shrink-0 rounded-full p-1 text-text-secondary hover:bg-surface-tertiary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-xheavy';
export const PRIMARY_BTN_CLASS =
  'flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-text-secondary hover:bg-surface-tertiary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-xheavy';
const MENU_CLASS =
  'z-50 min-w-[13rem] rounded-xl border border-border-light bg-surface-secondary p-1.5 text-text-primary shadow-lg outline-none';
const MENU_ITEM_CLASS =
  'flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-text-primary data-[active-item]:bg-surface-tertiary aria-disabled:cursor-not-allowed aria-disabled:opacity-50';
const ESCALATION_MESSAGE_LABEL_MAX_LENGTH = 80;

const activeEscalateListeners = new Set<() => void>();
let hoveredEscalateTarget: string | null = null;
let focusedEscalateTarget: string | null = null;

function getActiveEscalateTarget() {
  return focusedEscalateTarget ?? hoveredEscalateTarget;
}

function subscribeToActiveEscalateTarget(listener: () => void) {
  activeEscalateListeners.add(listener);
  return () => activeEscalateListeners.delete(listener);
}

function updateActiveEscalateTarget(kind: 'hover' | 'focus', targetId: string, active: boolean) {
  const previous = getActiveEscalateTarget();
  if (kind === 'hover') {
    if (active) {
      hoveredEscalateTarget = targetId;
    } else if (hoveredEscalateTarget === targetId) {
      hoveredEscalateTarget = null;
    }
  } else {
    if (active) {
      focusedEscalateTarget = targetId;
    } else if (focusedEscalateTarget === targetId) {
      focusedEscalateTarget = null;
    }
  }
  if (previous !== getActiveEscalateTarget()) {
    activeEscalateListeners.forEach((listener) => listener());
  }
}

function clearActiveEscalateTarget(targetId: string) {
  const previous = getActiveEscalateTarget();
  if (hoveredEscalateTarget === targetId) {
    hoveredEscalateTarget = null;
  }
  if (focusedEscalateTarget === targetId) {
    focusedEscalateTarget = null;
  }
  if (previous !== getActiveEscalateTarget()) {
    activeEscalateListeners.forEach((listener) => listener());
  }
}

export type MenuEntry = {
  key: string;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
};

/** Per-message actions only; sending preferences do not belong to a queued row. */
export function RowMenu({
  label,
  entries,
  buttonRef,
}: {
  label: string;
  entries: MenuEntry[];
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  const menu = Ariakit.useMenuStore({ placement: 'top-end' });
  if (entries.length === 0) {
    return null;
  }
  return (
    <>
      <Ariakit.MenuButton
        ref={buttonRef}
        store={menu}
        aria-label={label}
        className={ICON_BTN_CLASS}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </Ariakit.MenuButton>
      <Ariakit.Menu store={menu} portal gutter={6} className={MENU_CLASS}>
        {entries.map((entry) => (
          <Ariakit.MenuItem
            key={entry.key}
            className={MENU_ITEM_CLASS}
            disabled={entry.disabled === true}
            accessibleWhenDisabled
            onClick={() => {
              entry.onClick();
              menu.hide();
            }}
          >
            {entry.icon}
            {entry.label}
          </Ariakit.MenuItem>
        ))}
      </Ariakit.Menu>
    </>
  );
}

/**
 * The always-visible escalation control on a waiting message: interrupt &
 * steer it now, at the next safe token boundary. The tooltip teaches this
 * action's OWN shortcut (registry-aware, so a rebinding shows correctly).
 * Hover/focus marks this exact button as the active shortcut target; without
 * an active row the shortcut retains its newest-waiting-message fallback.
 */
export function EscalateNowButton({
  surface,
  disabled,
  messageText,
  onClick,
}: {
  surface: 'bubble' | 'queued';
  disabled: boolean;
  messageText: string;
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  const localize = useLocalize();
  const chord = useShortcutDisplay('escalateSteer');
  const ariaKey = useShortcutAriaKey('escalateSteer');
  const targetId = useId();
  const activeTarget = useSyncExternalStore(
    subscribeToActiveEscalateTarget,
    getActiveEscalateTarget,
    () => null,
  );
  const isActive = !disabled && activeTarget === targetId;
  const label = localize('com_ui_interrupt_steer_now');
  const normalizedMessageLabel = messageText.trim().replace(/\s+/g, ' ');
  const messageCharacters = Array.from(normalizedMessageLabel);
  const messageLabel =
    messageCharacters.length > ESCALATION_MESSAGE_LABEL_MAX_LENGTH
      ? `${messageCharacters
          .slice(0, ESCALATION_MESSAGE_LABEL_MAX_LENGTH - 1)
          .join('')
          .trimEnd()}…`
      : normalizedMessageLabel;
  const accessibleLabel = messageLabel.length > 0 ? `${label}: ${messageLabel}` : label;

  useEffect(() => {
    if (disabled) {
      clearActiveEscalateTarget(targetId);
    }
    return () => clearActiveEscalateTarget(targetId);
  }, [disabled, targetId]);

  return (
    <Ariakit.TooltipProvider placement="top" timeout={300}>
      <Ariakit.TooltipAnchor
        render={
          <button
            type="button"
            aria-label={accessibleLabel}
            aria-keyshortcuts={isActive ? ariaKey : undefined}
            data-escalate-steer={surface}
            data-escalate-steer-active={isActive ? 'true' : undefined}
            data-testid={surface === 'queued' ? 'queued-interrupt-now' : 'steer-escalate-now'}
            disabled={disabled}
            onPointerEnter={() => !disabled && updateActiveEscalateTarget('hover', targetId, true)}
            onPointerLeave={() => updateActiveEscalateTarget('hover', targetId, false)}
            onFocus={() => !disabled && updateActiveEscalateTarget('focus', targetId, true)}
            onBlur={() => updateActiveEscalateTarget('focus', targetId, false)}
            onClick={onClick}
            className={cn(
              'flex size-6 shrink-0 items-center justify-center rounded-full',
              'bg-text-primary text-surface-primary transition-opacity hover:opacity-85',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-xheavy',
              'disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:opacity-35',
            )}
          >
            <ArrowUp className="h-3.5 w-3.5" strokeWidth={2.4} aria-hidden="true" />
          </button>
        }
      />
      <Ariakit.Tooltip className="z-50 rounded-lg bg-surface-tertiary px-2 py-1 text-xs text-text-primary shadow-lg">
        {chord && isActive ? `${label} · ${chord}` : label}
      </Ariakit.Tooltip>
    </Ariakit.TooltipProvider>
  );
}
