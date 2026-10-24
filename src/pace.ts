/** Same gap rules as python/clippr/pace.py. Keep them in step. */

const HOLD_AFTER_SECONDS = 2;
const APPROACH_SECONDS = 2;
const MIN_SKIP_SECONDS = 1.5;

export function skippedSeconds(killTicks: number[], tickrate: number): number {
  const rate = tickrate >= 16 ? tickrate : 64;
  const hold = Math.max(1, Math.round(HOLD_AFTER_SECONDS * rate));
  const approach = Math.max(1, Math.round(APPROACH_SECONDS * rate));
  const minimum = Math.max(1, Math.round(MIN_SKIP_SECONDS * rate));
  const ticks = [...new Set(killTicks.filter((tick) => tick > 0))].sort((a, b) => a - b);
  let skipped = 0;
  for (let index = 0; index < ticks.length - 1; index += 1) {
    const leave = ticks[index] + hold;
    const arrive = ticks[index + 1] - approach;
    if (arrive - leave >= minimum) skipped += arrive - leave;
  }
  return skipped / rate;
}
