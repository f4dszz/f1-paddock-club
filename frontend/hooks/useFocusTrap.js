// frontend-completeness-6 (a11y) — focus management for slide-over modals.
//
// Moves focus into the panel on open, traps Tab/Shift+Tab inside it, restores
// focus to the previously-focused element on close, and calls onClose on Esc.
// Used by ExplainabilityPanel and SavedTrips so keyboard/screen-reader users
// are not stranded behind a slide-over.
import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(active, onClose) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    const previouslyFocused =
      typeof document !== "undefined" ? document.activeElement : null;

    const focusables = () =>
      container
        ? Array.from(container.querySelectorAll(FOCUSABLE)).filter(
            (el) => el.offsetParent !== null || el === document.activeElement
          )
        : [];

    // Move focus into the panel on open.
    const first = focusables()[0];
    if (first) first.focus();
    else if (container) {
      container.setAttribute("tabindex", "-1");
      container.focus();
    }

    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const activeEl = document.activeElement;
      if (e.shiftKey) {
        if (activeEl === firstEl || !container.contains(activeEl)) {
          e.preventDefault();
          lastEl.focus();
        }
      } else if (activeEl === lastEl || !container.contains(activeEl)) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Restore focus to the element that opened the panel.
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        previouslyFocused.focus();
      }
    };
  }, [active, onClose]);

  return containerRef;
}
