import * as React from "react";
import { useI18n } from "@/i18n";
import { caretAfterDigits, digitsBefore } from "@/lib/caret";
import { cn } from "@/lib/cn";
import { formatRaw, parseNumericInput } from "@/lib/format";

type Props = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "value" | "onChange" | "type" | "inputMode"
> & {
  /** Raw ASCII-digit string: what goes to the API. Never the formatted text. */
  value: string;
  onValueChange: (raw: string) => void;
  /** Translated unit shown inside the field. A number without its unit is incomplete. */
  unit: string;
  allowDecimal?: boolean;
  invalid?: boolean;
};

/**
 * The project's only numeric field. Holds two values: the raw string (state)
 * and the grouped, localized string (display). Never type="number": that
 * cannot show a group separator and scroll/spinner edits are wrong for data.
 */
export const NumericInput = React.forwardRef<HTMLInputElement, Props>(
  ({ value, onValueChange, unit, allowDecimal = false, invalid, className, ...props }, ref) => {
    const { locale } = useI18n();
    const inner = React.useRef<HTMLInputElement>(null);
    React.useImperativeHandle(ref, () => inner.current as HTMLInputElement);

    const display = formatRaw(value, locale);
    // Caret target as a count of digits before it; applied after the re-render.
    const pendingCaret = React.useRef<number | null>(null);

    React.useLayoutEffect(() => {
      const el = inner.current;
      if (el && pendingCaret.current !== null && document.activeElement === el) {
        const pos = caretAfterDigits(el.value, pendingCaret.current);
        el.setSelectionRange(pos, pos);
      }
      pendingCaret.current = null;
    });

    const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
      const el = event.target;
      const typed = el.value;
      const caret = el.selectionStart ?? typed.length;
      const raw = parseNumericInput(typed, allowDecimal);

      if (raw === null || raw === value) {
        // Rejected keystroke (a letter, a second decimal mark) or a no-op edit
        // (typing a separator): state will not change, so no re-render will
        // repair the DOM. Reset it here, synchronously.
        const pos =
          raw === null
            ? Math.max(0, Math.min(display.length, caret - (typed.length - display.length)))
            : caretAfterDigits(display, digitsBefore(typed, caret));
        el.value = display;
        el.setSelectionRange(pos, pos);
        return;
      }
      pendingCaret.current = digitsBefore(typed, caret);
      onValueChange(raw);
    };

    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-lg border bg-card px-3 transition-shadow",
          "focus-within:ring-2 focus-within:ring-ring",
          invalid && "border-destructive focus-within:ring-destructive",
          props.disabled && "opacity-60",
          className,
        )}
      >
        <input
          ref={inner}
          {...props}
          type="text"
          inputMode={allowDecimal ? "decimal" : "numeric"}
          autoComplete="off"
          aria-invalid={invalid || undefined}
          value={display}
          onChange={handleChange}
          className="nums min-w-0 flex-1 bg-transparent py-2 text-start outline-none"
        />
        <span className="shrink-0 select-none text-sm text-muted-foreground">{unit}</span>
      </div>
    );
  },
);
NumericInput.displayName = "NumericInput";
