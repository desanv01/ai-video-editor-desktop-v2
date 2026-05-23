export type EditorCommandId =
  | "play-pause"
  | "undo"
  | "redo"
  | "seek-backward"
  | "seek-forward"
  | "cut-selection"
  | "open-export"
  | "open-settings"
  | "open-command-palette";

export type CommandCategory = "Playback" | "Editing" | "Workspace" | "Navigation";

export type KeyBinding = {
  key: string;
  label: string;
  ctrlOrMeta?: boolean;
  shift?: boolean;
  alt?: boolean;
  preventDefault?: boolean;
};

export type EditorCommand = {
  id: EditorCommandId;
  label: string;
  category: CommandCategory;
  description?: string;
  bindings: KeyBinding[];
  disabledReason?: string;
  run: () => void | Promise<void>;
};

export function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;

  const tagName = target.tagName.toLowerCase();
  return (
    target.isContentEditable ||
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select"
  );
}

export function matchesKeyBinding(event: KeyboardEvent, binding: KeyBinding): boolean {
  const eventKey = normalizeKey(event.key);
  const bindingKey = normalizeKey(binding.key);
  const wantsModifier = Boolean(binding.ctrlOrMeta);

  if (eventKey !== bindingKey) return false;
  if (wantsModifier !== (event.ctrlKey || event.metaKey)) return false;
  if (Boolean(binding.shift) !== event.shiftKey) return false;
  if (Boolean(binding.alt) !== event.altKey) return false;

  return true;
}

export function primaryShortcutLabel(command: EditorCommand): string {
  return command.bindings[0]?.label ?? "";
}

function normalizeKey(key: string): string {
  if (key === " ") return "space";
  return key.toLowerCase();
}
