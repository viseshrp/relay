import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage } from "../api";

import type { ArtifactRecord, JsonValue, RunInteraction } from "../types";

import { object } from "./RunReviewShared";
export function useReviewRequest({
  interaction,
  runId,
  artifacts,
  selected,
  onAnswered,
}: {
  interaction: RunInteraction;
  runId: string;
  artifacts: ArtifactRecord[];
  selected: boolean;
  onAnswered: () => Promise<void>;
}) {
  const options = Array.isArray(interaction.request.options)
    ? interaction.request.options
    : [];
  const labelId = useId();
  const mode = object(object(options[0])?.mode);
  const schema = object(mode?.requestedSchema);
  const fields = object(schema?.properties);
  const required = Array.isArray(schema?.required) ? schema.required : [];
  const [value, setValue] = useState("");
  const [form, setForm] = useState<Record<string, JsonValue>>({});
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const card = useRef<HTMLDivElement | null>(null);
  const isReview = interaction.kind === "wait";
  const simpleForm =
    fields !== null &&
    Object.values(fields).every((field) => {
      const type = object(field)?.type;
      return (
        type === "string" ||
        type === "boolean" ||
        type === "number" ||
        type === "integer"
      );
    });
  useEffect(() => {
    if (selected)
      card.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected]);
  function link() {
    const url = new URL(window.location.href);
    url.searchParams.set("view", "runs");
    url.searchParams.set("run", runId);
    url.searchParams.set("interaction", interaction.id);
    return url.toString();
  }
  async function answer(decline = false, selectedAnswer?: string) {
    setBusy(true);
    setError(null);
    try {
      if (interaction.request.environment) {
        await api(`/api/attempts/${interaction.attempt_id}/environment`, {
          method: "POST",
          body: "{}",
        });
        await onAnswered();
        return;
      }
      let answerValue: JsonValue = selectedAnswer ?? value;
      if (interaction.kind === "elicitation") {
        answerValue = decline ? null : simpleForm ? form : JSON.parse(value);
        if (
          answerValue !== null &&
          (typeof answerValue !== "object" || Array.isArray(answerValue))
        )
          throw new Error("Enter the requested fields or decline the request.");
      }
      await api(`/api/attempts/${interaction.attempt_id}/${interaction.kind}`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          interaction_id: interaction.id,
          ...(interaction.kind === "permission"
            ? { decision: value }
            : { value: answerValue }),
          ...(!isReview && feedback.trim() ? { feedback } : {}),
        }),
      });
      await onAnswered();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  const ready = interaction.request.environment
    ? true
    : interaction.kind === "elicitation" && simpleForm
      ? required.every(
          (name) =>
            typeof name === "string" &&
            form[name] !== undefined &&
            form[name] !== "",
        )
      : value !== "";

  return {
    fallback: null as null,
    card,
    interaction,
    selected,
    isReview,
    link,
    runId,
    artifacts,
    options,
    busy,
    answer,
    labelId,
    value,
    setValue,
    simpleForm,
    fields,
    form,
    setForm,
    required,
    feedback,
    setFeedback,
    error,
    ready,
  };
}
export type ReviewRequestState = Extract<
  ReturnType<typeof useReviewRequest>,
  { fallback: null }
>;
