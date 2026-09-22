import { useState } from "react";
import { LANGUAGE_OPTIONS } from "../state/useTranscriberSession";

export interface SettingsPanelProps {
  language: string;
  onLanguageChange: (lang: string) => void;
  vocabularyHints: string;
  onVocabularyHintsChange: (hints: string) => void;
  supportsHints: boolean;
  providerLabel: string;
  disabled: boolean;
}

export function SettingsPanel(props: SettingsPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <section className="settings-panel">
      <button
        type="button"
        className="settings-panel__toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        Settings {open ? "▲" : "▼"}
      </button>
      {open && (
        <div className="settings-panel__body">
          <label className="settings-field">
            <span>Language</span>
            <select
              value={props.language}
              onChange={(e) => props.onLanguageChange(e.target.value)}
              disabled={props.disabled}
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.code} value={opt.code}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="settings-field">
            <span>
              Custom vocabulary (names, brands, terms){" "}
              {!props.supportsHints && <em className="settings-hint-note">— not supported by the current provider</em>}
            </span>
            <input
              type="text"
              placeholder="e.g. Youdao, R2T2, Anthropic"
              value={props.vocabularyHints}
              onChange={(e) => props.onVocabularyHintsChange(e.target.value)}
              disabled={props.disabled || !props.supportsHints}
            />
          </label>

          {props.providerLabel && (
            <p className="settings-provider-label">Engine: {props.providerLabel}</p>
          )}
        </div>
      )}
    </section>
  );
}
