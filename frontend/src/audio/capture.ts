/**
 * Browser microphone capture: getUserMedia -> AudioWorklet -> resampled
 * PCM16 frames, using AudioWorklet (not the deprecated ScriptProcessorNode)
 * so audio processing runs off the main thread. See
 * public/audio-worklet-processor.js for the actual downmix/resample.
 *
 * Deliberately does *not* decide whether to forward frames to the network
 * during Pause -- that's session-state policy, kept in useTranscriberSession.
 * This module's only job is: turn the microphone into a clean stream of
 * (level, frame) events, and release every OS/browser resource on stop().
 */

const TARGET_SAMPLE_RATE = 16000;
const FRAME_DURATION_S = 0.1; // 100ms frames -- see README "Performance" for the latency trade-off

export interface CaptureCallbacks {
  onLevel: (rmsDbfs: number) => void;
  onFrame: (pcm16: Int16Array) => void;
  onDeviceLost: () => void;
  onError: (message: string) => void;
}

export class AudioCapture {
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private silentGain: GainNode | null = null;
  private callbacks: CaptureCallbacks;

  constructor(callbacks: CaptureCallbacks) {
    this.callbacks = callbacks;
  }

  static async listInputDevices(): Promise<MediaDeviceInfo[]> {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audioinput");
  }

  async start(deviceId?: string): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser does not support microphone capture (getUserMedia).");
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: { ideal: 1 },
      },
    });

    for (const track of this.stream.getAudioTracks()) {
      track.addEventListener("ended", () => this.callbacks.onDeviceLost());
    }

    this.audioContext = new AudioContext();
    if (this.audioContext.state === "suspended") {
      // Some browsers suspend a freshly-created AudioContext until a user
      // gesture resumes it; Start is itself the user gesture, so this
      // should resolve immediately, but we guard against it hanging.
      await this.audioContext.resume();
    }

    await this.audioContext.audioWorklet.addModule("/audio-worklet-processor.js");

    this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
    this.workletNode = new AudioWorkletNode(this.audioContext, "pcm-capture-processor", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      processorOptions: {
        targetSampleRate: TARGET_SAMPLE_RATE,
        frameSamples: Math.round(TARGET_SAMPLE_RATE * FRAME_DURATION_S),
      },
    });

    this.workletNode.port.onmessage = (event: MessageEvent) => {
      const msg = event.data;
      if (msg.type === "level") {
        const rms = msg.rms as number;
        const dbfs = rms > 0 ? 20 * Math.log10(rms) : -120;
        this.callbacks.onLevel(Math.max(-120, dbfs));
      } else if (msg.type === "audio-frame") {
        this.callbacks.onFrame(new Int16Array(msg.buffer as ArrayBuffer));
      }
    };

    // The worklet must be connected into the render graph to be pulled
    // each quantum. We route it through a zero-gain node to destination so
    // it's actively processed without ever producing audible output --
    // connecting it directly to destination would risk feedback/echo.
    this.silentGain = this.audioContext.createGain();
    this.silentGain.gain.value = 0;
    this.sourceNode.connect(this.workletNode);
    this.workletNode.connect(this.silentGain);
    this.silentGain.connect(this.audioContext.destination);

    this.audioContext.addEventListener("statechange", () => {
      if (this.audioContext?.state === "suspended" || this.audioContext?.state === "interrupted") {
        this.callbacks.onError(
          "Audio processing was suspended by the browser (e.g. tab backgrounded or interrupted)."
        );
      }
    });
  }

  stop(): void {
    this.workletNode?.port.postMessage({ type: "stop" });
    this.workletNode?.port.close();
    this.sourceNode?.disconnect();
    this.workletNode?.disconnect();
    this.silentGain?.disconnect();
    for (const track of this.stream?.getTracks() ?? []) {
      track.stop();
    }
    void this.audioContext?.close();
    this.stream = null;
    this.audioContext = null;
    this.sourceNode = null;
    this.workletNode = null;
    this.silentGain = null;
  }

  get sampleRate(): number {
    return TARGET_SAMPLE_RATE;
  }
}
