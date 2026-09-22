/**
 * Runs on the audio rendering thread (AudioWorkletGlobalScope), separate
 * from the main thread, which is what lets capture keep up with real-time
 * audio without being blocked by React renders or network I/O.
 *
 * Responsibilities: downmix to mono, resample from the AudioContext's
 * native sample rate to the provider's required rate (16kHz), pack into
 * fixed-size Int16 PCM frames, and report a coarse RMS level for the meter.
 * Batched to ~1 postMessage/50ms per stream (not per 128-sample render
 * quantum) to keep main-thread message overhead low.
 */

// Maintains a continuously-correct fractional read position across many
// small `push()` calls, so resampling quality doesn't degrade at render-
// quantum (128-sample) boundaries.
class LinearResampler {
  constructor(inputRate, outputRate) {
    this.ratio = inputRate / outputRate;
    this.buffer = new Float32Array(0);
    this.pos = 0;
  }

  push(samples) {
    const merged = new Float32Array(this.buffer.length + samples.length);
    merged.set(this.buffer, 0);
    merged.set(samples, this.buffer.length);
    this.buffer = merged;

    const out = [];
    while (true) {
      const i0 = Math.floor(this.pos);
      const i1 = i0 + 1;
      if (i1 >= this.buffer.length) break;
      const frac = this.pos - i0;
      out.push(this.buffer[i0] * (1 - frac) + this.buffer[i1] * frac);
      this.pos += this.ratio;
    }

    const consumed = Math.floor(this.pos);
    if (consumed > 0) {
      this.buffer = this.buffer.slice(consumed);
      this.pos -= consumed;
    }
    return out;
  }
}

function floatToInt16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    out[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
  }
  return out;
}

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = options.processorOptions || {};
    this.targetSampleRate = opts.targetSampleRate || 16000;
    // sampleRate is a global provided by AudioWorkletGlobalScope: the
    // AudioContext's actual native rate (commonly 48000 or 44100).
    this.resampler = new LinearResampler(sampleRate, this.targetSampleRate);
    this.frameSamples = opts.frameSamples || Math.round(this.targetSampleRate * 0.1); // 100ms
    this._outCarry = [];
    this._rawWindow = [];
    // Flush a level update + any complete frames roughly every 50ms of
    // *input* audio, regardless of frame size, to bound message rate.
    this._levelWindowSamples = Math.round(sampleRate * 0.05);
    this._active = true;

    this.port.onmessage = (event) => {
      if (event.data?.type === "stop") {
        this._active = false;
      }
    };
  }

  _downmix(input) {
    if (input.length === 1) return input[0];
    const length = input[0].length;
    const mono = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let c = 0; c < input.length; c++) sum += input[c][i];
      mono[i] = sum / input.length;
    }
    return mono;
  }

  process(inputs) {
    if (!this._active) return false;
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0] || input[0].length === 0) {
      return true; // no audio yet this quantum; keep the node alive
    }

    const mono = this._downmix(input);
    for (let i = 0; i < mono.length; i++) this._rawWindow.push(mono[i]);

    const resampled = this.resampler.push(mono);
    for (let i = 0; i < resampled.length; i++) this._outCarry.push(resampled[i]);

    if (this._rawWindow.length >= this._levelWindowSamples) {
      let sumSq = 0;
      for (let i = 0; i < this._rawWindow.length; i++) sumSq += this._rawWindow[i] * this._rawWindow[i];
      const rms = Math.sqrt(sumSq / this._rawWindow.length);
      this._rawWindow = [];

      const frames = [];
      while (this._outCarry.length >= this.frameSamples) {
        const chunk = this._outCarry.splice(0, this.frameSamples);
        frames.push(floatToInt16(chunk).buffer);
      }

      this.port.postMessage({ type: "level", rms }, []);
      for (const buf of frames) {
        this.port.postMessage({ type: "audio-frame", buffer: buf }, [buf]);
      }
    }

    return true;
  }
}

registerProcessor("pcm-capture-processor", PCMCaptureProcessor);
