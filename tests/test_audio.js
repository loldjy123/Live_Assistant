const assert=require('assert');
let Processor;
global.AudioWorkletProcessor=class {constructor(){this.port={};}};
global.registerProcessor=(name,cls)=>{assert.equal(name,'pcm-processor');Processor=cls;};
require('../processor.js');
const p=new Processor();
p.port.onmessage({data:{audio:new Float32Array([.1,.2,.3])}});
let out=new Float32Array(4);
p.process([],[[out]]);
assert(Math.abs(out[2]-.3)<.0001);
assert.equal(out[3],0); // partial chunks must play instead of hanging forever
p.port.onmessage({data:{audio:new Float32Array([1,1,1,1])}});
p.port.onmessage({data:{clear:true}});
p.process([],[[out]]);
assert(out.every(x=>x===0)); // interruption must discard queued speech
console.log('Audio queue and interruption checks passed');
