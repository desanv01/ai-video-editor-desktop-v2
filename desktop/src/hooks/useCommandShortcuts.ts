import { useEffect } from "react";
import {
  isTextEntryTarget,
  matchesKeyBinding,
  type EditorCommand,
} from "../lib/editorCommands";

export function useCommandShortcuts(commands: EditorCommand[]) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isTextEntryTarget(event.target)) return;

      for (const command of commands) {
        const binding = command.bindings.find((candidate) => matchesKeyBinding(event, candidate));
        if (!binding) continue;

        if (binding.preventDefault !== false) event.preventDefault();
        if (!command.disabledReason) void command.run();
        return;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [commands]);
}
