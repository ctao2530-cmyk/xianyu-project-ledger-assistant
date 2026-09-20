import { useEffect, useRef } from 'react';
import { auroraBufferSize, auroraDefaults as config } from './auroraParameters';
import { auroraFragmentShader, auroraVertexShader } from './auroraShader';

/** Only the isolated fixture supplies this handle; there is no production URL/global test hook. */
export interface AuroraTestControls {
  time?: number;
  failure?: 'unavailable' | 'shader';
  lowPower?: boolean;
  setTime?: (time: number | undefined) => void;
}

export function AuroraBackground({ motion, testControls: fixtureControls }: { motion: 'auto' | 'off'; testControls?: AuroraTestControls }) {
  // Vite removes fixture-only clock/failure injection from production builds.
  const testControls = (import.meta as ImportMeta & { readonly env?: { readonly PROD?: boolean } }).env?.PROD ? undefined : fixtureControls;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current!;
    const host = hostRef.current!;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let gl: WebGL2RenderingContext | null = null;
    let program: WebGLProgram | null = null;
    let raf = 0, resizeFrame = 0, disposed = false, lost = false, restores = 0;
    let elapsed = 0, lastTick = 0, lastDraw = 0, frames = 0, width = 0, height = 0;
    let slowFrames = 0;
    let fps: number = testControls?.lowPower || navigator.hardwareConcurrency <= 4 ? config.lowPowerFps : config.fps;
    let resolution: WebGLUniformLocation | null = null, viewport: WebGLUniformLocation | null = null, time: WebGLUniformLocation | null = null;
    const status = (value: string) => { host.dataset.status = value; };
    const stop = () => { if (raf) cancelAnimationFrame(raf); raf = 0; lastTick = lastDraw = 0; host.dataset.loop = '0'; };
    const release = () => { if (program) gl?.deleteProgram(program); program = null; };
    const animate = () => motion === 'auto' && !reduced.matches && !document.hidden && testControls?.time === undefined;
    const resize = () => {
      width = host.clientWidth; height = host.clientHeight;
      const size = auroraBufferSize(width, height, devicePixelRatio || 1);
      if (canvas.width !== size.width || canvas.height !== size.height) { canvas.width = size.width; canvas.height = size.height; }
    };
    const draw = () => {
      if (!gl || !program || lost || disposed || !width || !height) return;
      gl.viewport(0, 0, canvas.width, canvas.height); gl.useProgram(program);
      gl.uniform2f(resolution, canvas.width, canvas.height); gl.uniform2f(viewport, width, height);
      const t = testControls?.time ?? (motion === 'off' || reduced.matches ? config.testTimeSeconds : elapsed);
      gl.uniform1f(time, t); gl.drawArrays(gl.TRIANGLES, 0, 3);
      host.dataset.time = t.toFixed(3); host.dataset.frames = String(++frames); host.dataset.fps = String(fps);
      status(animate() ? 'running' : 'static');
    };
    const tick = (now: number) => {
      raf = 0;
      if (disposed || lost || !program || !animate()) { stop(); return; }
      if (lastTick) {
        const delta = now - lastTick;
        elapsed += Math.min(delta, 100) / 1000;
        if (delta > 45 && ++slowFrames >= 90) fps = config.lowPowerFps;
      }
      lastTick = now;
      if (!lastDraw || now - lastDraw >= 1000 / fps - 0.5) { draw(); lastDraw = now; }
      raf = requestAnimationFrame(tick); host.dataset.loop = '1';
    };
    const sync = () => {
      stop();
      if (document.hidden) { status('paused'); return; }
      draw();
      if (program && !lost && animate()) { raf = requestAnimationFrame(tick); host.dataset.loop = '1'; }
    };
    const initialise = () => {
      const shaders: WebGLShader[] = [];
      try {
        if (testControls?.failure === 'unavailable') throw new Error('Unavailable');
        gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
        if (!gl) throw new Error('Unavailable');
        const compile = (kind: number, source: string) => {
          const shader = gl!.createShader(kind); if (!shader) throw new Error('Shader allocation'); shaders.push(shader);
          gl!.shaderSource(shader, source); gl!.compileShader(shader);
          if (!gl!.getShaderParameter(shader, gl!.COMPILE_STATUS)) throw new Error('Shader compilation'); return shader;
        };
        program = gl.createProgram(); if (!program) throw new Error('Program allocation');
        gl.attachShader(program, compile(gl.VERTEX_SHADER, auroraVertexShader));
        gl.attachShader(program, compile(gl.FRAGMENT_SHADER, testControls?.failure === 'shader' ? 'invalid' : auroraFragmentShader));
        gl.linkProgram(program); if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Program link');
        gl.useProgram(program);
        resolution = gl.getUniformLocation(program, 'uResolution'); viewport = gl.getUniformLocation(program, 'uViewport'); time = gl.getUniformLocation(program, 'uTime');
        gl.uniform1f(gl.getUniformLocation(program, 'uSeed'), config.seed);
        gl.uniform4f(gl.getUniformLocation(program, 'uMotion'), config.loopSeconds, config.breatheSeconds, config.horizontalTravel, config.verticalTravel);
        gl.uniform3f(gl.getUniformLocation(program, 'uMaterial'), config.breatheMin, config.breatheMax, config.grainOpacity);
        resize(); sync();
      } catch { stop(); release(); status('fallback'); }
      finally { shaders.forEach(shader => gl?.deleteShader(shader)); }
    };
    const onLost = (event: Event) => { event.preventDefault(); lost = true; stop(); release(); status('fallback'); };
    const onRestored = () => { if (disposed || restores >= 1) return; restores++; lost = false; initialise(); };
    canvas.addEventListener('webglcontextlost', onLost); canvas.addEventListener('webglcontextrestored', onRestored);
    document.addEventListener('visibilitychange', sync); reduced.addEventListener('change', sync);
    const onResize = () => { resize(); if (!document.hidden) draw(); };
    const observer = new ResizeObserver(onResize); observer.observe(host);
    window.addEventListener('resize', onResize);
    // A display/DPR change can leave the CSS viewport size unchanged.
    let pixelRatioQuery = matchMedia(`(resolution: ${devicePixelRatio}dppx)`);
    const onPixelRatioChange = () => {
      // Coalesce display changes before rebuilding the backing buffer.
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = 0;
        pixelRatioQuery.removeEventListener('change', onPixelRatioChange);
        pixelRatioQuery = matchMedia(`(resolution: ${devicePixelRatio}dppx)`);
        pixelRatioQuery.addEventListener('change', onPixelRatioChange);
        onResize();
      });
    };
    pixelRatioQuery.addEventListener('change', onPixelRatioChange);
    if (testControls) testControls.setTime = value => { testControls.time = value; sync(); };
    initialise();
    return () => {
      disposed = true; stop(); observer.disconnect(); window.removeEventListener('resize', onResize);
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      pixelRatioQuery.removeEventListener('change', onPixelRatioChange);
      document.removeEventListener('visibilitychange', sync); reduced.removeEventListener('change', sync);
      canvas.removeEventListener('webglcontextlost', onLost); canvas.removeEventListener('webglcontextrestored', onRestored);
      // Do not force context loss: StrictMode reuses this canvas during its setup/cleanup probe.
      release(); gl = null;
      if (testControls) delete testControls.setTime;
    };
  }, [motion, testControls]);
  return <div className="aurora-background" ref={hostRef} data-status="fallback" data-loop="0" aria-hidden="true"><canvas ref={canvasRef} /></div>;
}
