// A short synthesized "tick" (Web Audio, no sound file) played once a second
// while a hold timer runs. Browsers only let audio start from a tap, so
// unlockTickSound() must be called from one (the Start / Resume buttons);
// until then playTick() is silent.

let context: AudioContext | null = null

export function unlockTickSound() {
  const AudioCtor =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AudioCtor) return
  context ??= new AudioCtor()
  if (context.state === 'suspended') void context.resume()
}

export function playTick() {
  if (!context || context.state !== 'running') return
  const start = context.currentTime
  const osc = context.createOscillator()
  const gain = context.createGain()
  osc.type = 'square'
  osc.frequency.setValueAtTime(1600, start)
  // A ~50 ms click: fast attack, quick decay.
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.exponentialRampToValueAtTime(0.2, start + 0.003)
  gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.05)
  osc.connect(gain).connect(context.destination)
  osc.start(start)
  osc.stop(start + 0.06)
}
