// 設定(GET /api/config)。失敗時は組み込みの既定値を使う。
export const config = {
  future_years: 10,
  caller_name: '10年後の自分',
  record_min_sec: 20,
  record_max_sec: 90,
  ring_timeout_sec: 30,
  missed_call_display_sec: 4,
  end_screen_sec: 15,
  consent_idle_sec: 60,
  low_volume_threshold: 0.02,
  ringtone_volume: 0.8,
  call_volume: 1.0,
  staff_reset_hold_ms: 3000,
  status_poll_ms: 1000,
  max_wait_sec: 200,
  reply_wait_enabled: true,
  reply_no_speech_sec: 5,
  reply_silence_end_sec: 1.2,
  reply_max_sec: 15,
  reply_min_pause_sec: 0.6,
  reply_speech_threshold: 0.03,
  ambient_enabled: true,
  ambient_volume: 0.12,
  ambient_file: null,
};

export function applyConfig(obj) {
  if (!obj || typeof obj !== 'object') return;
  for (const k of Object.keys(config)) {
    if (obj[k] !== undefined && obj[k] !== null) config[k] = obj[k];
  }
}
