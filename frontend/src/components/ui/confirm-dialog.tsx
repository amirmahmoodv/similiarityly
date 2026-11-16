import { AnimatedDialogContent } from "@/components/motion";
import { useI18n } from "@/i18n";
import { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./dialog";
import { Button, ErrorNote } from "./primitives";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
  onConfirm: () => void;
  pending: boolean;
  error?: unknown;
  confirmLabel?: string;
  variant?: "danger" | "primary";
};

/** Confirmation for destructive or disruptive actions; stays open while pending or on error. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  onConfirm,
  pending,
  error,
  confirmLabel,
  variant = "danger",
}: Props) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <AnimatedDialogContent closeLabel={t.common.close} className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{body}</DialogDescription>
        </DialogHeader>
        {error ? <ErrorNote error={error} /> : null}
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={pending}>
            {t.common.cancel}
          </Button>
          <Button variant={variant} onClick={onConfirm} loading={pending}>
            {confirmLabel ?? t.common.delete}
          </Button>
        </DialogFooter>
      </AnimatedDialogContent>
    </Dialog>
  );
}
