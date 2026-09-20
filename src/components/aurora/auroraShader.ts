// Original analytic S-curves and deterministic grain, written for this project.
// No third-party noise implementation, textures or postprocessing.
export const auroraVertexShader = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;
export const auroraFragmentShader = `#version 300 es
precision highp float;
uniform vec2 uResolution;
uniform vec2 uViewport;
uniform float uTime;
uniform float uSeed;
uniform vec4 uMotion; // shape period, breath period, horizontal and vertical travel
uniform vec3 uMaterial; // breath min/max, grain opacity
out vec4 outColor;
float ribbon(float distance, float width) { return exp(-pow(distance / width, 2.0)); }
void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  uv.y = 1.0 - uv.y;
  float phase = 6.28318530718 * uTime / uMotion.x;
  // Keep the stronger drift within a comfortable fraction of narrow viewports.
  vec2 travel = min(uMotion.zw, uViewport * vec2(0.16, 0.08));
  vec2 shift = travel * vec2(sin(phase), cos(phase)) / uViewport;
  vec2 p = uv + shift;
  float mainY = 0.59 - 0.73 * p.x + 0.115 * sin(5.2 * p.x + 0.28 * sin(phase));
  float secondY = 0.39 - 0.12 * p.x + 0.075 * sin(5.8 * p.x - 0.22 * cos(phase));
  float farY = 0.94 - 0.52 * p.x + 0.06 * sin(4.1 * p.x + 0.2 * sin(phase));
  float d = p.y - mainY;
  float primary = ribbon(d, 0.043) * 0.58 + ribbon(d + 0.047, 0.11) * 0.19;
  float folds = 0.82 + 0.18 * sin(71.0 * p.x + 30.0 * p.y + 0.55 * sin(phase));
  float light = primary * folds + ribbon(p.y - secondY, 0.026) * 0.26 + ribbon(p.y - farY, 0.088) * 0.18;
  float breath = mix(uMaterial.x, uMaterial.y, 0.5 + 0.5 * sin(6.28318530718 * uTime / uMotion.y));
  // Grain is tied to ribbon coordinates. No frame-random flicker.
  vec2 grainCell = floor(p * uViewport * 0.85);
  float grain = fract(sin(dot(grainCell, vec2(12.9898, 78.233)) + uSeed) * 43758.5453);
  float shade = 1.0 - 0.30 * smoothstep(0.2, 0.85, uv.y);
  vec3 base = vec3(0.012, 0.027, 0.022);
  vec3 green = vec3(0.10, 0.62, 0.35) * light * breath * shade;
  green += (grain - 0.5) * uMaterial.z * smoothstep(0.01, 0.35, light);
  outColor = vec4(base + green, 1.0);
}`;
