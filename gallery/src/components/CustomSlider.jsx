import React, { useEffect, useRef, useState } from "react";

/* Custom Slider — React port of the design handoff's
   `Custom Slider.dc.html` (drift §48). A drag track + thumb that replaces the
   native <input type=range>; `onChange` is handed the NUMERIC value, not an
   event. Colours are the comp's var(--*) tokens verbatim (surface1 track,
   mauve→lavender fill).

   The `compact` prop (default OFF, so every other usage is unchanged) shrinks it
   for tight slots like the separator-bar SIZE pill: thumb 12/15px · track 4px ·
   padding 6px, exactly the numbers the drift item names.

   Ported from a DCLogic class to a function component; the drag math
   (valueFromClientX, the window mouse/touch listeners, the drag-grow thumb) is
   line-for-line the comp's. Keyboard support (arrow keys) is added on top —
   parity with the native range it replaces, since a bare div has none. */
export default function CustomSlider({
  value,
  min = 0,
  max = 1,
  step = 1,
  disabled = false,
  compact = false,
  onChange,
  ariaLabel,
}) {
  const wrapRef = useRef(null);
  const endRef = useRef(null); // teardown for an in-flight drag (unmount safety)
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => { if (endRef.current) endRef.current(); }, []);

  const clientX = (ev) => (ev.touches ? ev.touches[0].clientX : ev.clientX);

  const valueFromClientX = (cx) => {
    const el = wrapRef.current;
    if (!el) return value ?? min;
    const rect = el.getBoundingClientRect();
    let pct = rect.width ? (cx - rect.left) / rect.width : 0;
    pct = Math.max(0, Math.min(1, pct));
    let v = min + pct * (max - min);
    v = Math.round(v / step) * step;
    v = Math.max(min, Math.min(max, v));
    return Math.round(v * 1000) / 1000;
  };

  const start = (ev) => {
    if (disabled) return;
    if (ev.cancelable) ev.preventDefault();
    const commit = (e) => {
      const v = valueFromClientX(clientX(e));
      if (onChange) onChange(v);
    };
    const end = () => {
      setDragging(false);
      window.removeEventListener("mousemove", commit);
      window.removeEventListener("mouseup", end);
      window.removeEventListener("touchmove", commit);
      window.removeEventListener("touchend", end);
      endRef.current = null;
    };
    endRef.current = end;
    setDragging(true);
    commit(ev);
    window.addEventListener("mousemove", commit);
    window.addEventListener("mouseup", end);
    window.addEventListener("touchmove", commit, { passive: true });
    window.addEventListener("touchend", end);
  };

  const v = Math.max(min, Math.min(max, value ?? min));
  const pct = max > min ? ((v - min) / (max - min)) * 100 : 0;
  const size = compact ? (dragging ? 15 : 12) : (dragging ? 20 : 16);

  const onKeyDown = (e) => {
    if (disabled || !onChange) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      onChange(Math.max(min, v - step)); e.preventDefault();
    } else if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      onChange(Math.min(max, v + step)); e.preventDefault();
    } else if (e.key === "Home") {
      onChange(min); e.preventDefault();
    } else if (e.key === "End") {
      onChange(max); e.preventDefault();
    }
  };

  return (
    <div
      ref={wrapRef}
      role="slider"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={v}
      aria-label={ariaLabel}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? undefined : 0}
      onMouseDown={start}
      onTouchStart={start}
      onKeyDown={onKeyDown}
      style={{
        position: "relative",
        padding: (compact ? "6px" : "11px") + " 0",
        touchAction: "none",
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.45 : 1,
      }}
    >
      <div
        style={{
          position: "relative",
          height: (compact ? 4 : 5) + "px",
          borderRadius: "999px",
          background: "var(--surface1)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: pct + "%",
            borderRadius: "999px",
            background: "linear-gradient(90deg, var(--mauve), var(--lavender))",
            boxShadow: disabled
              ? undefined
              : "0 0 10px -1px color-mix(in srgb, var(--lavender) 65%, transparent)",
          }}
        />
      </div>
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: pct + "%",
          width: size + "px",
          height: size + "px",
          transform: "translate(-50%, -50%)",
          borderRadius: "50%",
          background: "#fff",
          border: "2px solid var(--lavender)",
          boxShadow:
            "0 2px 8px rgba(0,0,0,.5)" +
            (dragging ? ", 0 0 0 5px color-mix(in srgb, var(--lavender) 32%, transparent)" : ""),
          transition: "width .12s ease, height .12s ease, box-shadow .15s ease",
        }}
      />
    </div>
  );
}
