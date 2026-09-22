import { Banner } from "./components/Banner";
import { StatusBadge } from "./components/StatusBadge";
import { Controls } from "./components/Controls";
import { TranscriptView } from "./components/TranscriptView";
import { Actions } from "./components/Actions";
import { SettingsPanel } from "./components/SettingsPanel";
import { useTranscriberSession } from "./state/useTranscriberSession";

export default function App() {
  const session = useTranscriberSession();
  const settingsLocked = session.appState !== "idle" && session.appState !== "complete" && session.appState !== "error";

  return (
    <div className="app">
      <header className="app-header">
        <h1>Live Transcriber</h1>
        <StatusBadge state={session.appState} />
      </header>

      {session.errorMessage && <Banner kind="error" message={session.errorMessage} />}
      {session.warningMessage && !session.errorMessage && (
        <Banner kind="warning" message={session.warningMessage} onDismiss={session.dismissWarning} />
      )}

      <Controls
        appState={session.appState}
        levelDbfs={session.levelDbfs}
        elapsedMs={session.elapsedMs}
        micDevices={session.micDevices}
        selectedDeviceId={session.selectedDeviceId}
        onSelectDevice={session.selectDevice}
        onStart={session.start}
        onPause={session.pause}
        onResume={session.resume}
        onStop={session.stop}
      />

      <SettingsPanel
        language={session.language}
        onLanguageChange={session.setLanguage}
        vocabularyHints={session.vocabularyHints}
        onVocabularyHintsChange={session.setVocabularyHints}
        supportsHints={session.supportsHints}
        providerLabel={session.providerLabel}
        disabled={settingsLocked}
      />

      <main className="transcript-main">
        <TranscriptView
          committed={session.committed}
          tentativeText={session.tentativeText}
          isEditable={session.isEditable}
          editableValue={session.transcriptText}
          onEdit={session.setEditedText}
        />
      </main>

      <Actions
        transcriptText={session.transcriptText}
        canClear={session.appState === "complete" || session.appState === "error"}
        onClear={session.clearSession}
      />

      <footer className="app-footer">
        <p>
          Audio is processed on this server via WebSocket and is never sent to a third-party cloud
          API. Nothing is recorded to disk unless you download the transcript yourself.
        </p>
      </footer>
    </div>
  );
}
