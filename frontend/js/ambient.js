// 通話中の環境音。既定は Web Audio でオリジナルの「カフェ/部屋のざわめき」を生成する。
// 電話の帯域(300〜3400Hz)に絞り、ごく小さく流す。ambient_file があればそれをループ再生(失敗時は生成音)。
import { getAudioContext } from './audio.js';

const rnd = (a, b) => a + Math.random() * (b - a);

export class Ambient {
  constructor({ volume = 0.12, file = null } = {}) {
    this.ctx = getAudioContext();
    this.volume = volume; this.file = file;
    this.nodes = []; this.timers = new Set(); this.stopped = false;
    const c = this.ctx;
    this.master = c.createGain(); this.master.gain.value = 0;
    this.hp = c.createBiquadFilter(); this.hp.type = 'highpass'; this.hp.frequency.value = 300; this.hp.Q.value = 0.7;
    this.lp = c.createBiquadFilter(); this.lp.type = 'lowpass'; this.lp.frequency.value = 3400; this.lp.Q.value = 0.7;
    this.soft = c.createBiquadFilter(); this.soft.type = 'lowpass'; this.soft.frequency.value = 2600; this.soft.Q.value = 0.3;
    this.bus = c.createGain(); // 生成音/ファイル共通の入口
    this.bus.connect(this.hp); this.hp.connect(this.lp); this.lp.connect(this.soft); this.soft.connect(this.master);
    this.master.connect(c.destination);
  }

  start() {
    const c = this.ctx, t = c.currentTime;
    this.master.gain.setValueAtTime(0, t);
    this.master.gain.linearRampToValueAtTime(this.volume, t + 1.5);
    if (this.file) {
      this._loadFile(this.file).then((ok) => { if (!ok && !this.stopped) this._generate(); });
    } else {
      this._generate();
    }
  }

  async _loadFile(url) {
    try {
      const res = await fetch(url, { cache: 'force-cache' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
      if (this.stopped) return true;
      const s = this.ctx.createBufferSource();
      s.buffer = buf; s.loop = true; s.connect(this.bus); s.start();
      this.nodes.push(s);
      return true;
    } catch (e) { return false; }
  }

  _later(fn, ms) {
    const id = setTimeout(() => { this.timers.delete(id); if (!this.stopped) fn(); }, ms);
    this.timers.add(id);
  }

  _noiseBuffer() {
    const c = this.ctx, len = Math.floor(c.sampleRate * 4);
    const b = c.createBuffer(1, len, c.sampleRate), d = b.getChannelData(0);
    let b0 = 0, b1 = 0, b2 = 0; // ピンクノイズ (Paul Kellet)
    for (let i = 0; i < len; i++) {
      const w = Math.random() * 2 - 1;
      b0 = 0.99765 * b0 + w * 0.0990460; b1 = 0.96300 * b1 + w * 0.2965164; b2 = 0.57000 * b2 + w * 1.0526913;
      d[i] = (b0 + b1 + b2 + w * 0.1848) * 0.2;
    }
    return b;
  }

  _noise(dest) {
    const s = this.ctx.createBufferSource();
    s.buffer = this._nb; s.loop = true;
    s.start(0, rnd(0, 3));
    s.connect(dest);
    this.nodes.push(s);
    return s;
  }

  _generate() {
    const c = this.ctx;
    this._nb = this._noiseBuffer();

    // 部屋の空気(ごく低いノイズ)
    const room = c.createGain(); room.gain.value = 0.25;
    const roomLp = c.createBiquadFilter(); roomLp.type = 'lowpass'; roomLp.frequency.value = 700;
    this._noise(roomLp); roomLp.connect(room); room.connect(this.bus);

    // ざわめき(ゆっくり揺れるバンドパスノイズ)
    const mur = c.createGain(); mur.gain.value = 0.5;
    const murBp = c.createBiquadFilter(); murBp.type = 'bandpass'; murBp.frequency.value = 650; murBp.Q.value = 0.6;
    this._noise(murBp); murBp.connect(mur); mur.connect(this.bus);
    const wobble = () => {
      const t = c.currentTime, d = rnd(1.5, 4);
      mur.gain.linearRampToValueAtTime(rnd(0.25, 0.7), t + d);
      murBp.frequency.linearRampToValueAtTime(rnd(450, 1000), t + d);
      this._later(wobble, d * 1000);
    };
    wobble();

    // 遠くの話し声(言葉にならない音節状の包絡を持つバンドパスノイズ)
    for (let v = 0; v < 3; v++) this._voice(rnd(0.6, 1.4));

    // 食器の音
    this._later(() => this._clink(), rnd(1500, 4000));
  }

  _voice(base) {
    const c = this.ctx;
    const g = c.createGain(); g.gain.value = 0;
    const bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 2.2; bp.frequency.value = rnd(400, 900) * base;
    const bp2 = c.createBiquadFilter(); bp2.type = 'bandpass'; bp2.Q.value = 3; bp2.frequency.value = rnd(1200, 2200);
    const pan = c.createStereoPanner ? c.createStereoPanner() : null;
    const out = c.createGain(); out.gain.value = rnd(0.35, 0.6);
    this._noise(bp); bp.connect(g);
    this._noise(bp2); bp2.connect(g);
    let last = g;
    if (pan) { pan.pan.value = rnd(-0.7, 0.7); g.connect(pan); last = pan; }
    last.connect(out); out.connect(this.bus);
    const phrase = () => {
      const n = 3 + Math.floor(Math.random() * 6);
      let t = 0;
      for (let i = 0; i < n; i++) {
        const dur = rnd(0.08, 0.2), gap = rnd(0.04, 0.12);
        const when = c.currentTime + t + 0.02;
        const f = rnd(350, 1100) * base;
        g.gain.setValueAtTime(0, when);
        g.gain.linearRampToValueAtTime(rnd(0.5, 1), when + dur * 0.35);
        g.gain.linearRampToValueAtTime(0, when + dur);
        bp.frequency.setTargetAtTime(f, when, 0.02);
        t += dur + gap;
      }
      this._later(phrase, (t + rnd(0.6, 4)) * 1000);
    };
    this._later(phrase, rnd(0, 2500));
  }

  _clink() {
    const c = this.ctx, t = c.currentTime + 0.02;
    const base = rnd(1800, 3600), amp = rnd(0.05, 0.12);
    const pan = c.createStereoPanner ? c.createStereoPanner() : null;
    const out = c.createGain(); out.gain.value = 1;
    let dest = this.bus;
    if (pan) { pan.pan.value = rnd(-0.8, 0.8); pan.connect(this.bus); dest = pan; }
    out.connect(dest);
    [[1, 1], [2.76, 0.5], [5.4, 0.25]].forEach(([r, a]) => {
      const o = c.createOscillator(); o.type = 'sine'; o.frequency.value = base * r;
      const g = c.createGain(), dec = rnd(0.12, 0.45) / r ** 0.3;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(amp * a, t + 0.003);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dec);
      o.connect(g); g.connect(out); o.start(t); o.stop(t + dec + 0.05);
      o.onended = () => { try { o.disconnect(); g.disconnect(); } catch (e) {} };
    });
    // まれに 2 連続(カチャ、カチャ)
    if (Math.random() < 0.3) this._later(() => this._clink(), rnd(120, 300));
    else this._later(() => this._clink(), rnd(3500, 9000));
  }

  stop(fast = false) {
    if (this.stopped) return;
    this.stopped = true;
    this.timers.forEach(clearTimeout); this.timers.clear();
    const c = this.ctx, t = c.currentTime, d = fast ? 0.12 : 0.9;
    try {
      this.master.gain.cancelScheduledValues(t);
      this.master.gain.setValueAtTime(this.master.gain.value, t);
      this.master.gain.linearRampToValueAtTime(0, t + d);
    } catch (e) {}
    setTimeout(() => {
      for (const n of this.nodes) { try { n.stop(); } catch (e) {} try { n.disconnect(); } catch (e) {} }
      this.nodes = [];
      try { this.master.disconnect(); this.bus.disconnect(); } catch (e) {}
    }, d * 1000 + 100);
  }
}
