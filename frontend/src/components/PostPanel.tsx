import { useEffect, useState } from "react";
import { api, errorText } from "../lib/api";
import { cx } from "../lib/format";
import type { Clip, SocialSuggestions } from "../lib/types";
import { Button, LinkButton } from "./ui";

const KIND_LABEL: Record<string, string> = {
  niche: "niche",
  topic: "from your speech",
  language: "audience",
  broad: "broad",
  ai: "AI",
};

/** Caption + hashtag suggestions and a copy-to-clipboard, for posting a rendered clip. */
export default function PostPanel({ projectId, clip }: { projectId: string; clip: Clip }) {
  const [data, setData] = useState<SocialSuggestions | null>(null);
  const [caption, setCaption] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function load(ai: boolean) {
    setLoading(true);
    setError(null);
    try {
      const r = await api.clipSocial(projectId, clip.id, ai);
      setData(r);
      setCaption(r.captions[0]?.text ?? "");
      setPicked(new Set(r.hashtags.slice(0, 6).map((h) => h.tag)));
    } catch (e) {
      setError(errorText(e, "Couldn't build suggestions."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.id]);

  const tags = (data?.hashtags ?? []).filter((h) => picked.has(h.tag)).map((h) => h.tag);
  const full = [caption.trim(), tags.join(" ")].filter(Boolean).join("\n\n");

  async function copy() {
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Couldn't copy automatically — select the text and copy it yourself.");
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">
        Suggestions are built from what you say in this clip, on your PC. They're starting points — edit freely. Instagram works best with a few
        relevant tags, so the first six are pre-selected.
      </p>
      {error && <div className="text-xs text-red-300">{error}</div>}
      {data?.note && <div className="text-xs text-amber-300">{data.note}</div>}

      <div className="space-y-1.5">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Caption ideas</div>
        <div className="flex flex-wrap gap-1.5">
          {(data?.captions ?? []).map((c, i) => (
            <button
              key={i}
              onClick={() => setCaption(c.text)}
              title={c.text}
              className={cx(
                "rounded-full border px-2.5 py-1 text-xs",
                caption === c.text ? "border-accent text-accent" : "border-surface-border text-slate-300 hover:border-slate-500"
              )}
            >
              {c.style}
            </button>
          ))}
        </div>
        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          rows={3}
          className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent"
        />
      </div>

      <div className="space-y-1.5">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Hashtags ({tags.length} selected)</div>
        <div className="flex flex-wrap gap-1.5">
          {(data?.hashtags ?? []).map((h) => {
            const on = picked.has(h.tag);
            return (
              <button
                key={h.tag}
                title={KIND_LABEL[h.kind] ?? h.kind}
                onClick={() =>
                  setPicked((p) => {
                    const n = new Set(p);
                    if (n.has(h.tag)) n.delete(h.tag);
                    else n.add(h.tag);
                    return n;
                  })
                }
                className={cx(
                  "rounded-full border px-2.5 py-1 text-xs",
                  on ? "border-accent bg-accent/15 text-accent" : "border-surface-border text-slate-400 hover:border-slate-500"
                )}
              >
                {h.tag}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={copy} disabled={!full}>
          {copied ? "Copied ✓" : "Copy caption + hashtags"}
        </Button>
        <Button onClick={() => load(true)} disabled={loading} title="Uses your local Ollama model; can take up to a minute">
          {loading ? "Working..." : "✨ Improve with local AI"}
        </Button>
        {clip.render.status === "done" && (
          <LinkButton href={api.clipDownloadUrl(projectId, clip.id)} download>
            ⬇ MP4
          </LinkButton>
        )}
      </div>

      <p className="rounded-lg bg-surface p-2 text-xs text-slate-500">
        One-click posting to Instagram isn't built yet — download the MP4, then paste this caption in the Instagram app or on instagram.com.
      </p>
    </div>
  );
}
