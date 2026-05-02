"use client";

/**
 * features/chat/components/SlashTurnBlock.tsx — Render a slash-command
 * "turn" inline in the chat log.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): pure render — no SSE / abort
 * coupling — so extraction is mechanical.
 *
 * Shows the typed input as a small user bubble and the structured card as
 * if it were the assistant's reply. Visually identical placement so the
 * conversation reads naturally.
 */

import { SlashCommandCard } from "@/components/chat/SlashCommandCard";
import type { SlashTurn } from "../lib/types";

export function SlashTurnBlock({ turn }: { turn: SlashTurn }) {
  return (
    <>
      {/* User echo of the typed input — matches the regular user-message style */}
      <div className="flex flex-col items-end gap-1">
        <div className="flex max-w-[70%] items-end gap-2 flex-row-reverse">
          <div className="rounded-[2px] bg-primary/10 px-4 py-3 text-sm">
            <pre className="whitespace-pre-wrap font-sans text-sm">{turn.input}</pre>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">
              {new Date(turn.created_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          </div>
        </div>
      </div>
      {/* The card itself — fetched on render via TanStack Query */}
      <SlashCommandCard command={turn.command} />
    </>
  );
}
