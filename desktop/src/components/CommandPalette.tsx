import { useEffect, useMemo, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Search, X } from "lucide-react";
import { primaryShortcutLabel, type EditorCommand } from "../lib/editorCommands";

export type CommandPaletteCommand = EditorCommand & {
  icon: LucideIcon;
};

type Props = {
  isOpen: boolean;
  commands: CommandPaletteCommand[];
  onClose: () => void;
};

export function CommandPalette({ isOpen, commands, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filteredCommands = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return commands;

    return commands.filter((command) => {
      const haystack = `${command.label} ${command.category} ${command.description ?? ""}`.toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [commands, query]);

  useEffect(() => {
    if (!isOpen) return;

    setQuery("");
    setSelectedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex((index) => clampCommandIndex(index, filteredCommands.length));
  }, [filteredCommands.length]);

  if (!isOpen) return null;

  const runCommand = (command: CommandPaletteCommand) => {
    if (command.disabledReason) return;
    void command.run();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh]">
      <div className="w-full max-w-2xl overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-2xl">
        <div className="flex items-center gap-3 border-b border-surface-border px-3 py-3">
          <Search className="h-4 w-4 text-gray-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                onClose();
              }
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setSelectedIndex((index) => clampCommandIndex(index + 1, filteredCommands.length));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setSelectedIndex((index) => clampCommandIndex(index - 1, filteredCommands.length));
              }
              if (event.key === "Enter") {
                event.preventDefault();
                const selected = filteredCommands[selectedIndex];
                if (selected) runCommand(selected);
              }
            }}
            placeholder="Search editor commands"
            className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-gray-600"
          />
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-200"
            aria-label="Close command palette"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[56vh] overflow-y-auto p-2">
          {filteredCommands.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-gray-500">No commands found.</div>
          ) : (
            <div className="space-y-1">
              {filteredCommands.map((command, index) => {
                const Icon = command.icon;
                const isSelected = selectedIndex === index;
                const shortcut = primaryShortcutLabel(command);
                const disabled = Boolean(command.disabledReason);

                return (
                  <button
                    key={command.id}
                    type="button"
                    disabled={disabled}
                    onMouseEnter={() => setSelectedIndex(index)}
                    onClick={() => runCommand(command)}
                    className={`flex w-full items-center gap-3 rounded px-3 py-2.5 text-left transition-colors ${
                      isSelected ? "bg-accent/15 text-white" : "text-gray-300 hover:bg-surface-overlay"
                    } ${disabled ? "cursor-not-allowed opacity-55" : ""}`}
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-surface-overlay text-gray-300">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold">{command.label}</span>
                      <span className="block truncate text-xs text-gray-500">
                        {command.disabledReason ?? command.category}
                      </span>
                    </span>
                    {shortcut && (
                      <kbd className="rounded border border-surface-border bg-surface-overlay px-2 py-1 font-mono text-[11px] text-gray-400">
                        {shortcut}
                      </kbd>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function clampCommandIndex(index: number, commandCount: number): number {
  if (commandCount <= 0) return 0;
  return Math.min(Math.max(index, 0), commandCount - 1);
}
