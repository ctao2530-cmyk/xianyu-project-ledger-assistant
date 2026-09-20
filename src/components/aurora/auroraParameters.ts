/** September 19 motion refinement. Shape math is original; no external shader/noise dependency. */
export const auroraDefaults = {
  seed: 17, ribbonCount: 3, loopSeconds: 24, breatheSeconds: 8,
  breatheMin: 0.92, breatheMax: 1.08, grainOpacity: 0.03,
  pointerParallax: false, fps: 30, lowPowerFps: 20,
  renderScale: 0.65, pixelRatioCap: 1.25, maxBufferPixels: 1_200_000,
  testTimeSeconds: 8, horizontalTravel: 120, verticalTravel: 60,
} as const;

export function auroraBufferSize(width: number, height: number, dpr: number) {
  const scale = auroraDefaults.renderScale * Math.min(Math.max(dpr, 1), auroraDefaults.pixelRatioCap);
  const budget = Math.min(1, Math.sqrt(auroraDefaults.maxBufferPixels / Math.max(1, width * height * scale * scale)));
  return { width: Math.max(1, Math.floor(width * scale * budget)), height: Math.max(1, Math.floor(height * scale * budget)) };
}
