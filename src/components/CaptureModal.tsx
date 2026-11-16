import { useState } from "react";
import { Zap } from "lucide-react";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import { Button, Input, Modal } from "./ui";

export function CaptureModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const config = useStore((state) => state.config);
  const notify = useStore((state) => state.notify);
  const [text, setText] = useState("");
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!config?.vault || !text.trim()) return;
    setBusy(true);
    try {
      const result = await api.capture(config.vault, text.trim(), tag.trim() || undefined);
      notify("Captured to inbox", result.path, "success");
      setText("");
      setTag("");
      onClose();
    } catch (error) {
      notify("Capture failed", error instanceof Error ? error.message : String(error), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Quick capture"
      description="A thought between lectures. It lands in your vault inbox, not the void."
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={busy} onClick={submit} icon={<Zap className="h-4 w-4" />}>
            Capture
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <textarea
          autoFocus
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submit();
          }}
          placeholder="The professor said the exam loves this distinction…"
          className="input min-h-32 resize-none"
        />
        <Input
          value={tag}
          onChange={(event) => setTag(event.target.value)}
          placeholder="tag (optional) — e.g. exam, weak-spot"
        />
      </div>
    </Modal>
  );
}
