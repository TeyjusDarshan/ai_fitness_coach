// Set by vite.config.ts at build time, so each deploy shows a different
// stamp — a quick way to check which version a device is running.
declare const __BUILD_TIME__: string

export const BUILD_LABEL = `Version ${new Date(__BUILD_TIME__).toLocaleString('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
})}`
