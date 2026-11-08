// GPU grading; keep this transform in sync with color_grade.grade_rgb.
const gradeDefaults = {brightness:1,contrast:1,saturation:1,exposure:0,vibrance:0,temperature:0,tint:0,shadows:0,highlights:0};
let gradeGpu;
function gradedVideo(vid, clip) {
  if (!clip || Object.entries(gradeDefaults).every(([k,v]) => (clip[k] ?? v) === v)) return vid;
  if (!gradeGpu) {
    const canvas = document.createElement('canvas'), gl = canvas.getContext('webgl',{premultipliedAlpha:false,preserveDrawingBuffer:true});
    if (!gl) return vid;
    const shader = (type,src) => {const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
    const program=gl.createProgram();
    gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.0)*0.5;gl_Position=vec4(p,0,1);}'));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision highp float; varying vec2 uv; uniform sampler2D image;
      uniform float brightness,contrast,saturation,exposure,vibrance,temperature,tint,shadows,highlights;
      void main(){vec3 c=texture2D(image,vec2(uv.x,1.0-uv.y)).rgb;
      c=(c*exp2(exposure)*brightness-0.5)*contrast+0.5;
      c+=vec3(0.1*temperature+0.05*tint,-0.1*tint,-0.1*temperature+0.05*tint);
      float l=clamp(dot(c,vec3(.2126,.7152,.0722)),0.0,1.0);
      c+=0.25*(shadows*(1.0-l)*(1.0-l)+highlights*l*l);
      l=dot(c,vec3(.2126,.7152,.0722));
      float chroma=min(1.0,max(c.r,max(c.g,c.b))-min(c.r,min(c.g,c.b)));
      c=vec3(l)+(c-vec3(l))*max(0.0,saturation+vibrance*(1.0-chroma));
      gl_FragColor=vec4(clamp(c,0.0,1.0),1.0);}`));
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
    const p=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
    const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gradeGpu={canvas,gl,program};
  }
  const {canvas,gl,program}=gradeGpu;
  if (canvas.width!==vid.videoWidth || canvas.height!==vid.videoHeight) {canvas.width=vid.videoWidth;canvas.height=vid.videoHeight;gl.viewport(0,0,canvas.width,canvas.height);}
  for(const [k,v] of Object.entries(gradeDefaults)) gl.uniform1f(gl.getUniformLocation(program,k),clip[k] ?? v);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,vid);
  gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
  return canvas;
}
