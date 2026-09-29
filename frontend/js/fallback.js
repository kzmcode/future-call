// 最終フォールバック: ブラウザの音声合成(speechSynthesis)で読み上げる。
// 内蔵テンプレートは、サーバーが使えないときのみ利用する。

export function fallbackScript(years) {
  const y = years || 10;
  const templates = [
    [
      'もしもし、聞こえるかな。' + y + '年後の、あなたです。',
      'ちょっとだけ、昔の話をさせてね。',
      'ねえ、あのときのこと、覚えてる?',
      'うん、うん。あのとき、うまくいかなくて、くやしかったよね。',
      'でもね、あの日のことは、ちゃんと私の力になっているよ。',
      'あきらめずに、もう一度やってみたから、今の私がいるんだ。',
      'うまくいかない日があっても、大丈夫。',
      '失敗は、つづきの始まりだよ。',
      'これからも、あなたらしく進んでね。応援しているよ。',
    ],
    [
      'もしもし、' + y + '年後のあなただよ。',
      '今日はね、どうしても伝えたくて電話したんだ。',
      'あの挑戦のこと、覚えてる?',
      'うん、そうだよね。今でもよく思い出すよ。',
      '思いどおりにならなくて、落ち込んだよね。',
      'でも、あの経験のおかげで、たくさんの友だちや仲間に出会えたんだ。',
      'だから、失敗をこわがらなくていいんだよ。',
      'あなたの一歩は、ちゃんと未来につながっているからね。',
      'それじゃあ、またね。',
    ],
    [
      'もしもし。' + y + '年後の私だよ。元気にしてる?',
      'うん、うん。あのときの気持ち、私はよく覚えているよ。',
      '悔しくて、ちょっと泣いちゃったこともあったね。',
      'でもね、その悔しさが、私をずっと支えてくれたんだ。',
      'ゆっくりでも、少しずつ前に進めば、ちゃんと道はひらけるよ。',
      'だから、今日のことを、たからものにしてね。',
      'ずっと、あなたの味方だよ。',
    ],
  ];
  const k = Math.floor(Math.random() * templates.length);
  return { sentences: templates[k], waitAfter: [[2], [2], [0]][k] };
}

export function fallbackSentences(years) { return fallbackScript(years).sentences; }

function pickVoice() {
  try {
    const vs = speechSynthesis.getVoices().filter((v) => /^ja/i.test(v.lang));
    if (!vs.length) return null;
    return vs.find((v) => /kyoko|o-ren|haruka|nanami|ayumi|google/i.test(v.name)) || vs[0];
  } catch (e) { return null; }
}

// sentences を順に読み上げる。戻り値 { cancel } 。完了時に onDone。
export function speak(sentences, { volume = 1, onDone, waitAfter = [], onWait } = {}) {
  const waits = new Set(waitAfter);
  let cancelled = false, idx = 0, finished = false;
  let watchdog = null;
  const synth = 'speechSynthesis' in window ? window.speechSynthesis : null;

  const done = () => {
    if (finished) return;
    finished = true; clearTimeout(watchdog);
    if (!cancelled && onDone) onDone();
  };

  const next = () => {
    clearTimeout(watchdog);
    if (cancelled || finished) return;
    if (idx >= sentences.length) { done(); return; }
    const my = idx;
    const text = sentences[idx++];
    const wait = Math.max(3000, text.length * 500 + 1500);
    let advanced = false;
    const adv = () => {
      if (advanced) return; advanced = true;
      clearTimeout(watchdog);
      if (onWait && waits.has(my) && idx < sentences.length) {
        // 返事待ち: 再開は resume() が呼ばれてから
        onWait(() => { if (!cancelled) setTimeout(next, 150); });
        return;
      }
      setTimeout(next, 150);
    };
    watchdog = setTimeout(adv, wait);
    if (!synth) return;
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'ja-JP'; u.pitch = 0.85; u.rate = 0.95; u.volume = Math.max(0, Math.min(1, volume));
      const v = pickVoice(); if (v) u.voice = v;
      u.onend = adv; u.onerror = adv;
      synth.speak(u);
    } catch (e) { /* watchdog が進める */ }
  };

  try { if (synth) synth.cancel(); } catch (e) {}
  next();

  return {
    cancel() {
      cancelled = true; clearTimeout(watchdog);
      try { if (synth) synth.cancel(); } catch (e) {}
    },
  };
}
