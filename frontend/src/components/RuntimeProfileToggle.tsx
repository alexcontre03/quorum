import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import type { RuntimeProfile, RuntimeSettings } from "../api";

const PROFILE_LABEL: Record<RuntimeProfile, string> = {
  local: "Local",
  openai: "OpenAI",
  anthropic: "Anthropic",
};

const DEFAULT_OPTION = "__default__";

/**
 * Compact runtime toggle that lives in the top navigation. A segmented
 * control switches the provider; the dropdown beside it switches the
 * model for the active provider. Both selections persist on the backend.
 */
export function RuntimeProfileToggle() {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getRuntimeSettings()
      .then((res) => {
        if (alive) setSettings(res);
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : "Failed to load runtime settings");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function switchProfile(next: RuntimeProfile) {
    if (!settings || next === settings.profile || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.setRuntimeProfile(next);
      setSettings(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to switch profile");
    } finally {
      setBusy(false);
    }
  }

  async function pickModel(value: string) {
    if (!settings || busy) return;
    setBusy(true);
    setError(null);
    try {
      const model = value === DEFAULT_OPTION ? null : value;
      const res = await api.setChatModel(settings.profile, model);
      setSettings(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to set model");
    } finally {
      setBusy(false);
    }
  }

  const modelOptions = useMemo(() => {
    if (!settings) return [];
    const known = settings.known_models[settings.profile] || [];
    const override = settings.model_overrides[settings.profile];
    const defaultModel = settings.default_models[settings.profile];
    // Drop the default model from the regular list: it already has its own
    // entry at the top labelled "Por defecto · <modelo>". Listing it twice
    // confuses the user into thinking we offer the same model twice.
    let filtered = defaultModel ? known.filter((m) => m !== defaultModel) : [...known];
    // Surface a custom override (set via .env or API) that is not in the
    // catalogue so the user can see what is actually active.
    if (override && override !== defaultModel && !filtered.includes(override)) {
      filtered = [override, ...filtered];
    }
    return filtered;
  }, [settings]);

  if (error) {
    return (
      <div className="runtime-toggle runtime-toggle-error" title={error}>
        runtime: error
      </div>
    );
  }

  if (!settings) {
    return <div className="runtime-toggle runtime-toggle-loading">runtime: …</div>;
  }

  const currentOverride = settings.model_overrides[settings.profile];
  const defaultModel = settings.default_models[settings.profile];
  const selectValue = currentOverride ?? DEFAULT_OPTION;

  return (
    <div className="runtime-toggle" aria-busy={busy}>
      <div className="runtime-toggle-buttons" role="radiogroup" aria-label="Runtime provider">
        {settings.allowed_profiles.map((p) => (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={settings.profile === p}
            disabled={busy}
            className={`runtime-toggle-button${settings.profile === p ? " active" : ""}`}
            onClick={() => switchProfile(p)}
          >
            {PROFILE_LABEL[p]}
          </button>
        ))}
      </div>
      <select
        className="runtime-toggle-select"
        value={selectValue}
        disabled={busy}
        onChange={(event) => pickModel(event.target.value)}
        aria-label="Model"
      >
        <option value={DEFAULT_OPTION}>
          {settings.profile === "local"
            ? "per-agent default"
            : defaultModel
            ? `Por defecto · ${defaultModel}`
            : "default"}
        </option>
        {modelOptions.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </div>
  );
}
