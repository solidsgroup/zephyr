import { useLayoutEffect, useRef, useState } from "react";

let measurementCanvas: HTMLCanvasElement | null = null;

export default function PathTail({ value }: { value: string }) {
  const element = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(value);

  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return;
    let active = true;

    const update = () => {
      const width = node.getBoundingClientRect().width;
      if (!active || width <= 0) {
        if (active) setDisplay(value);
        return;
      }
      measurementCanvas ??= document.createElement("canvas");
      const context = measurementCanvas.getContext("2d");
      if (!context) return;
      const style = window.getComputedStyle(node);
      context.font = style.font || `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const letterSpacing = Number.parseFloat(style.letterSpacing) || 0;
      const measure = (text: string) => context.measureText(text).width + Math.max(0, text.length - 1) * letterSpacing;
      const available = Math.max(0, width - 2);
      if (measure(value) <= available) {
        setDisplay(value);
        return;
      }
      let low = 0;
      let high = value.length;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (measure(`…${value.slice(middle)}`) <= available) high = middle;
        else low = middle + 1;
      }
      setDisplay(`…${value.slice(low)}`);
    };

    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(node);
    void document.fonts?.ready.then(update);
    return () => {
      active = false;
      observer?.disconnect();
    };
  }, [value]);

  return <span ref={element} className="path-tail" title={value} aria-label={value}>{display}</span>;
}
