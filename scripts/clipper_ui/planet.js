// An orthographic ray/sphere intersection gives a true spherical surface,
// without a framework or mesh download. Only the texture turns; sunlight stays fixed.
(() => {
  const canvas = document.getElementById('planet-canvas');
  const fallback = document.getElementById('planet-fallback');
  const gl = canvas.getContext('webgl', {alpha: true, antialias: false, depth: false, premultipliedAlpha: false});
  if (!gl) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const vertex = `attribute vec2 position; varying vec2 point;
    void main(){point=position;gl_Position=vec4(position,0.,1.);}`;
  const fragment = `precision highp float;
    varying vec2 point; uniform sampler2D surface; uniform float angle; uniform float pixels;
    void main(){
      vec2 p=point/.94; float r2=dot(p,p);
      if(r2>=1.){gl_FragColor=vec4(0.);return;}
      vec3 normal=vec3(p,sqrt(1.-r2));
      // A modest fixed axial tilt; the poles remain in place throughout rotation.
      float tilt=.10; mat2 axis=mat2(cos(tilt),-sin(tilt),sin(tilt),cos(tilt));
      vec2 local=axis*normal.xy;
      float longitude=atan(local.x,normal.z)/6.28318530718+.5+angle;
      float latitude=acos(clamp(local.y,-1.,1.))/3.14159265359;
      vec3 color=texture2D(surface,vec2(fract(longitude),latitude)).rgb;
      // Match the subdued, dusty color of the approved spacecraft photograph.
      float gray=dot(color,vec3(.2126,.7152,.0722));
      color=mix(vec3(gray),color,.48)*vec3(1.12,1.10,1.08);
      vec3 light=normalize(vec3(-.7,.5,1.45));
      float diffuse=max(dot(normal,light),0.);
      color*=.34+.88*pow(diffuse,.65);
      float haze=pow(1.-normal.z,3.)*.035*diffuse;
      color+=vec3(.58,.49,.40)*haze;
      float edge=1.-smoothstep(1.-4./pixels,1.,r2);
      gl_FragColor=vec4(color,edge);
    }`;
  let program = null, buffer = null, texture = null, angleLocation, pixelsLocation;
  let frame = 0, previous = 0, lastPaint = 0, elapsed = 0, ready = false, lost = false;
  const image = new Image();
  function dispose() {
    if (program) gl.deleteProgram(program);
    if (buffer) gl.deleteBuffer(buffer);
    if (texture) gl.deleteTexture(texture);
    program = buffer = texture = null;
  }
  function shader(type, text) {
    const result = gl.createShader(type);
    gl.shaderSource(result, text); gl.compileShader(result);
    if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) { gl.deleteShader(result); throw new Error('Planet shader unavailable'); }
    return result;
  }
  function render() {
    if (!ready || lost) return;
    const size = Math.max(1, Math.min(768, Math.round(canvas.getBoundingClientRect().width * Math.min(devicePixelRatio || 1, 2))));
    if (canvas.width !== size || canvas.height !== size) canvas.width = canvas.height = size;
    gl.viewport(0, 0, size, size);
    gl.useProgram(program);
    // One turn in four minutes, with no jump after returning to the page.
    gl.uniform1f(angleLocation, .03 + elapsed / 240);
    gl.uniform1f(pixelsLocation, size);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }
  function tick(now) {
    frame = 0;
    if (!ready || lost || document.hidden || reduced.matches) return;
    if (previous) elapsed += Math.min((now - previous) / 1000, .1);
    previous = now;
    if (now - lastPaint >= 1000 / 30) { render(); lastPaint = now; }
    frame = requestAnimationFrame(tick);
  }
  function resume() {
    cancelAnimationFrame(frame); frame = 0; previous = 0;
    if (!ready || lost || document.hidden) return;
    render();
    if (!reduced.matches) frame = requestAnimationFrame(tick);
  }
  function initialize() {
    let vs, fs;
    try {
      dispose();
      vs = shader(gl.VERTEX_SHADER, vertex); fs = shader(gl.FRAGMENT_SHADER, fragment);
      program = gl.createProgram(); gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Planet rendering unavailable');
      gl.useProgram(program);
      buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]), gl.STATIC_DRAW);
      const position = gl.getAttribLocation(program, 'position');
      gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
      gl.uniform1i(gl.getUniformLocation(program, 'surface'), 0);
      angleLocation = gl.getUniformLocation(program, 'angle'); pixelsLocation = gl.getUniformLocation(program, 'pixels');
      ready = true; canvas.hidden = false; render(); fallback.hidden = true; resume();
    } catch {
      ready = false; canvas.hidden = true; fallback.hidden = false; dispose();
    } finally { if (vs) gl.deleteShader(vs); if (fs) gl.deleteShader(fs); }
  }
  canvas.addEventListener('webglcontextlost', event => {
    event.preventDefault(); lost = true; cancelAnimationFrame(frame);
    canvas.hidden = true; fallback.hidden = false;
  });
  canvas.addEventListener('webglcontextrestored', () => { lost = false; if (image.complete && image.naturalWidth) initialize(); });
  document.addEventListener('visibilitychange', resume);
  reduced.addEventListener('change', resume);
  new ResizeObserver(() => { if (!document.hidden) render(); }).observe(canvas.parentElement);
  window.addEventListener('pagehide', () => { cancelAnimationFrame(frame); previous = 0; });
  window.addEventListener('pageshow', resume);
  image.onload = initialize;
  image.src = '/assets/mars-texture.jpg';
})();
