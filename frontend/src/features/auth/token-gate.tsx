import { useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button, Field, TextInput } from "@/components/ui/primitives";
import { useI18n } from "@/i18n";
import { getApiToken, setApiToken, UNAUTHORIZED_EVENT } from "@/lib/api";

/**
 * Asks for the server's access token (SIM_API_TOKEN) whenever the API answers
 * 401. Renders nothing on a server without a token.
 */
export function TokenGate() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [value, setValue] = React.useState("");
  const [rejected, setRejected] = React.useState(false);

  React.useEffect(() => {
    const onUnauthorized = () => {
      // A token was already in use, so the server refused it.
      setRejected(Boolean(getApiToken()));
      setOpen(true);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const token = value.trim();
    if (!token) return;
    setApiToken(token);
    setValue("");
    setOpen(false);
    void queryClient.invalidateQueries();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent closeLabel={t.common.close}>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRound className="size-5 text-primary" aria-hidden="true" />
              {t.auth.title}
            </DialogTitle>
            <DialogDescription>{t.auth.description}</DialogDescription>
          </DialogHeader>
          <Field label={t.auth.token} error={rejected ? t.auth.rejected : undefined}>
            {(ids) => (
              <TextInput
                {...ids}
                type="password"
                dir="ltr"
                autoComplete="current-password"
                spellCheck={false}
                autoFocus
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            )}
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={!value.trim()}>
              {t.auth.submit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
