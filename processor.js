class PCMProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.chunks=[];
        this.offset=0;
        this.port.onmessage=event=>{
            if(event.data.clear){this.chunks=[];this.offset=0;return;}
            if(event.data.audio?.length)this.chunks.push(event.data.audio);
        };
    }
    process(inputs,outputs) {
        const channel=outputs[0]?.[0];
        if(!channel)return true;
        channel.fill(0);
        let written=0;
        while(this.chunks.length && written<channel.length){
            const chunk=this.chunks[0];
            const count=Math.min(chunk.length-this.offset,channel.length-written);
            channel.set(chunk.subarray(this.offset,this.offset+count),written);
            written+=count;this.offset+=count;
            if(this.offset===chunk.length){this.chunks.shift();this.offset=0;}
        }
        return true;
    }
}
registerProcessor('pcm-processor',PCMProcessor);
