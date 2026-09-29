// AudioWorklet で生 PCM を取得し、16bit モノラル WAV にエンコードする。
import { getAudioContext } from './audio.js';

const WORKLET_SRC = `
class PcmCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
`;

let workletReady = null;
function ensureWorklet(ctx) {
  if (!workletReady) {
    const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'application/javascript' }));
    workletReady = ctx.audioWorklet.addModule(url).catch((e) => { workletReady = null; throw e; });
  }
  return workletReady;
}

export function encodeWav(chunks, sampleRate) {
  let total = 0;
  for (const c of chunks) total += c.length;
  const buf = new ArrayBuffer(44 + total * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + total * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, total * 2, true);
  let o = 44;
  for (const c of chunks) {
    for (let i = 0; i < c.length; i++) {
      const s = Math.max(-1, Math.min(1, c[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      o += 2;
    }
  }
  return new Blob([buf], { type: 'audio/wav' });
}

export class Recorder {
  constructor() {
    this.stream = null; this.source = null; this.node = null; this.sink = null;
    this.chunks = []; this.samples = 0; this.sampleRate = 48000; this.onLevel = null;
  }

  get elapsed() { return this.samples / this.sampleRate; }

  async start(onLevel) {
    this.onLevel = onLevel;
    const ctx = getAudioContext();
    if (ctx.state !== 'running') await ctx.resume();
    this.sampleRate = ctx.sampleRate;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    try {
      this.source = ctx.createMediaStreamSource(this.stream);
      const handle = (f32) => {
        this.chunks.push(f32); this.samples += f32.length;
        let sum = 0;
        for (let i = 0; i < f32.length; i++) sum += f32[i] * f32[i];
        if (this.onLevel) this.onLevel(Math.sqrt(sum / f32.length));
      };
      let node = null;
      if (ctx.audioWorklet) {
        try {
          await ensureWorklet(ctx);
          node = new AudioWorkletNode(ctx, 'pcm-capture', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit' });
          node.port.onmessage = (e) => handle(e.data);
        } catch (e) { node = null; }
      }
      if (!node) {
        node = ctx.createScriptProcessor(4096, 1, 1);
        node.onaudioprocess = (e) => handle(new Float32Array(e.inputBuffer.getChannelData(0)));
      }
      this.node = node;
      this.sink = ctx.createGain(); this.sink.gain.value = 0;
      this.source.connect(node); node.connect(this.sink); this.sink.connect(ctx.destination);
    } catch (e) {
      this._release();
      throw e;
    }
  }

  _release() {
    try { if (this.node) { this.node.onaudioprocess = null; if (this.node.port) this.node.port.onmessage = null; this.node.disconnect(); } } catch (e) {}
    try { if (this.source) this.source.disconnect(); } catch (e) {}
    try { if (this.sink) this.sink.disconnect(); } catch (e) {}
    if (this.stream) this.stream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
    this.stream = this.source = this.node = this.sink = null;
    this.onLevel = null;
  }

  stop() {
    const durationSec = this.elapsed;
    this._release();
    const blob = encodeWav(this.chunks, this.sampleRate);
    this.chunks = []; this.samples = 0;
    return { blob, durationSec };
  }

  cancel() {
    this._release();
    this.chunks = []; this.samples = 0;
  }
}
