import { useEffect, useState } from "react";

export function selectionRange(ids: string[], anchorId: string | null, targetId: string | null) {
  if (!anchorId || !targetId) return new Set<string>();
  const anchorIndex = ids.indexOf(anchorId);
  const targetIndex = ids.indexOf(targetId);
  if (anchorIndex < 0 || targetIndex < 0) return new Set<string>();
  const first = Math.min(anchorIndex, targetIndex);
  const last = Math.max(anchorIndex, targetIndex);
  return new Set(ids.slice(first, last + 1));
}

export function useShiftPressed() {
  const [pressed, setPressed] = useState(false);

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === "Shift") setPressed(true);
    };
    const keyUp = (event: KeyboardEvent) => {
      if (event.key === "Shift") setPressed(false);
    };
    const clear = () => setPressed(false);
    window.addEventListener("keydown", keyDown);
    window.addEventListener("keyup", keyUp);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("keydown", keyDown);
      window.removeEventListener("keyup", keyUp);
      window.removeEventListener("blur", clear);
    };
  }, []);

  return pressed;
}
