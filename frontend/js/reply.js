// 疑似的なやりとり: 体験者の返事(声)の有無を音量(RMS)だけで検知する。
// 録音・送信・保存は一切しない。判定が終わったら(または cancel で)マイクを必ず止める。
import { getAudioContext } from './audio.js';

// 戻り値 { promise, cancel, getAnalyser }。promise は続きを再生してよいタイミングで resolve (reject しない)。
export function detectReply(cfg, { onSpeaking } = {}) {
  let done = false, timer = null, stream = null, src = null, an = null, resolveFn;
  const promise = new Promise((r) => { resolveFn = r; });
  const t0 = performance.now();

  const finish = (why) => {
    if (done) return;
    done = true;
    clearInterval(timer); clearTimeout(timer);
    try { stream && stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
    try { src && src.disconnect(); } catch (e) {}
    stream = null; src = null; an = null;
    resolveFn(why);
  };

  const fixedWait = () => { timer = setTimeout(() => finish('fixed'), 2500); };

  (async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false, channelCount: 1 },
      });
      if (done) { s.getTracks().forEach((t) => t.stop()); return; }
      stream = s;
      const ctx = getAudioContext();
      src = ctx.createMediaStreamSource(s);
      an = ctx.createAnalyser();
      an.fftSize = 1024;
      src.connect(an); // destination には繋がない(自分の声を流さない)
    } catch (e) {
      if (!done) fixedWait();
      return;
    }
    const buf = new Float32Array(an.fftSize);
    const evalStart = t0 + cfg.reply_min_pause_sec * 1000;
    let above = 0, speaking = false, speechStart = 0, lastVoice = 0, prev = performance.now();
    timer = setInterval(() => {
      if (done || !an) return;
      const now = performance.now(), dt = now - prev; prev = now;
      an.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      if (now < evalStart) return;
      const loud = rms > cfg.reply_speech_threshold;
      if (!speaking) {
        above = loud ? above + dt : 0;
        if (above >= 150) { speaking = true; speechStart = now; lastVoice = now; if (onSpeaking) onSpeaking(); }
        else if (now - evalStart > cfg.reply_no_speech_sec * 1000) finish('no_speech');
      } else {
        if (loud) lastVoice = now;
        if (now - lastVoice > cfg.reply_silence_end_sec * 1000) finish('silence');
        else if (now - speechStart > cfg.reply_max_sec * 1000) finish('max');
      }
    }, 40);
  })();

  return { promise, cancel: () => finish('cancel'), getAnalyser: () => an };
}
