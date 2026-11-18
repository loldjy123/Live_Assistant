'use strict';
const $ = id => document.getElementById(id);
const configuredBackend = window.LIBRARY_CONFIG?.backendUrl?.trim();
const staticHosting = location.hostname.endsWith('.github.io');
let backendBase;

function backendEndpoint(path) {
    return new URL(path, backendBase);
}

async function verifyBackend() {
    const candidates = [backendBase];
    const localPreview = !configuredBackend && location.protocol === 'http:'
        && ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)
        && backendBase.port !== '8080';
    if (localPreview) {
        const localServer = new URL('/', location.href);
        localServer.port = '8080';
        candidates.push(localServer);
    }

    let failure;
    for (const candidate of candidates) {
        try {
            const response = await fetch(new URL('health', candidate), {
                cache: 'no-store',
                signal: AbortSignal.timeout(10000),
            });
            if (!response.ok) {
                failure = new Error('The live service is unavailable. Please retry shortly.');
                continue;
            }
            const health = await response.json();
            if (health.app !== 'live-book-inventory' || health.websocket_path !== '/ws') {
                failure = new Error('An older or incompatible server is running. Restart it with the current app, then refresh this page.');
                continue;
            }
            if (!health.ready) {
                failure = new Error('The live service is still starting. Please retry shortly.');
                continue;
            }
            backendBase = candidate;
            return;
        } catch {
            failure = new Error('Cannot reach the live service. Start the server or wait for your hosted service to wake up, then retry.');
        }
    }
    throw failure;
}

try {
    backendBase = configuredBackend
        ? new URL(configuredBackend.replace(/\/?$/, '/'))
        : staticHosting ? null : new URL('/', location.href);
    if (backendBase && !['http:', 'https:'].includes(backendBase.protocol)) {
        throw new Error('The service URL must use HTTP or HTTPS.');
    }
    if (backendBase && location.protocol === 'https:' && backendBase.protocol !== 'https:') {
        throw new Error('The live service must use HTTPS.');
    }
} catch (failure) {
    backendBase = null;
    $('errors').textContent = failure.message;
}
let socket, playback, worklet, microphone, camera, recorder, inputContext;
let audioTimer, frameTimer, pcm = [], ready = false, capturing = false;

function status(text) { $('status').textContent = text; }
function error(error) { $('errors').textContent = error.message || String(error); }
function send(message) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); }
function command(name, args) { send({command:name,args}); }
function encode(bytes) { let binary = ''; for (const value of bytes) binary += String.fromCharCode(value); return btoa(binary); }

async function setupPlayback() {
    playback = new AudioContext({sampleRate:24000});
    await playback.audioWorklet.addModule(new URL('processor.js', document.baseURI).href);
    worklet = new AudioWorkletNode(playback, 'pcm-processor');
    worklet.connect(playback.destination);
    await playback.resume();
}
function play(encoded) {
    if (!worklet) return;
    const binary = atob(encoded), buffer = new ArrayBuffer(binary.length), view = new DataView(buffer);
    for (let i=0;i<binary.length;i++) view.setUint8(i,binary.charCodeAt(i));
    const samples = new Float32Array(binary.length/2);
    for (let i=0;i<samples.length;i++) samples[i] = view.getInt16(i*2,true)/32768;
    worklet.port.postMessage({audio:samples});
}
function flushAudio() {
    if (!pcm.length) return;
    const bytes = new Uint8Array(pcm.length*2), view = new DataView(bytes.buffer);
    pcm.forEach((value,i) => view.setInt16(i*2,value,true));
    pcm = [];
    if (ready && capturing) send({audio:encode(bytes),sample_rate:inputContext.sampleRate});
}
function captureFrame() {
    if (!ready || !capturing || !$('video').videoWidth) return;
    const canvas = $('capture'), video = $('video');
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video,0,0);
    send({frame:canvas.toDataURL('image/jpeg',0.92).split(',')[1]});
}
async function openMicrophone() {
    microphone = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    inputContext = new AudioContext({sampleRate:16000});
    await inputContext.resume();
    recorder = inputContext.createScriptProcessor(1024,1,1);
    inputContext.createMediaStreamSource(microphone).connect(recorder);
    recorder.onaudioprocess = event => {
        if (!capturing || !ready) return;
        for (const value of event.inputBuffer.getChannelData(0)) pcm.push(Math.round(Math.max(-1,Math.min(1,value))*32767));
    };
    recorder.connect(inputContext.destination); // output stays silent; never monitor the microphone
    audioTimer = setInterval(flushAudio,100);
}
function stopCapture() {
    capturing = false;
    clearInterval(audioTimer); clearInterval(frameTimer); pcm = [];
    if (recorder) recorder.disconnect();
    microphone?.getTracks().forEach(track=>track.stop());
    camera?.getTracks().forEach(track=>track.stop());
    if (inputContext && inputContext.state !== 'closed') inputContext.close().catch(error);
    $('finish').disabled = true;
}
function renderInventory(packet) {
    const rows = packet.books.filter(book => book.kind === 'book' && book.title?.trim() && book.status !== 'unidentified' && !book.excluded && !book.duplicate_of && !book.possible_duplicate_of);
    $('inventory').replaceChildren();
    for (const book of rows) {
        const tr = document.createElement('tr');
        const amount = price => price ? `${price.amount} ${price.currency}` : 'Unknown';
        for (const value of [book.title,({identified:'Identified',researching:'Researching',priced:'Priced',needs_review:'Needs review'})[book.stage] || 'Pending',amount(book.replacement_cost),amount(book.used_value)]) {
            const td = document.createElement('td'); td.textContent = value; tr.append(td);
        }
        $('inventory').append(tr);
    }
    const totals = packet.totals;
    const currency = packet.sweep.currency;
    $('bookTotals').textContent = `Books identified: ${totals.books_identified} of ${totals.book_count} detected · Replacement total: ${totals.books_replacement_cost.toFixed(2)} ${currency} · Used total: ${totals.books_used_value.toFixed(2)} ${currency}`;

}
function receive(event) {
    const message = JSON.parse(event.data);
    if (message.ready) { ready=true; status('Recording'); $('finish').disabled=false; captureFrame(); }
    if (message.inventory) renderInventory(message.inventory);
    if (message.interrupted) worklet?.port.postMessage({clear:true});
    if (message.audio) play(message.audio);
    if (message.error) error(message.error);
    if (message.confirm_finish) { status('Click Finish sweep to confirm.'); $('finish').focus(); }
    if (message.report_ready) {
        status('Report ready');
        for (const [label,url] of [['Open HTML report',message.report_ready.html],['Download claim JSON',message.report_ready.json]]) {
            const link=document.createElement('a'); link.href=backendEndpoint(url).href; link.textContent=label; link.target='_blank'; link.rel='noopener'; if (label.includes('JSON')) link.download='claim_packet.json'; $('report').append(link);
        }
        $('new').hidden=false;
    }
}
$('start').onclick = async () => {
    if (!$('country').value.trim() || !/^[A-Za-z]{3}$/.test($('currency').value.trim())) { error('Enter a country and three-letter currency code.'); return; }
    $('start').disabled=true; $('errors').textContent=''; status('Requesting camera and microphone…');
    try {
        await setupPlayback();
        status('Connecting to live service…');
        await verifyBackend();
        camera = await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1920},height:{ideal:1080},facingMode:{ideal:'environment'}},audio:false});
        $('video').srcObject=camera; await $('video').play();
        capturing=true;
        await openMicrophone();
        const socketUrl = backendEndpoint('ws');
        socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(socketUrl.href);
        socket.onopen = () => send({locale:{country:$('country').value.trim(),currency:$('currency').value.trim().toUpperCase()},device:navigator.userAgent});
        socket.onmessage = receive;
        socket.onerror = () => error('WebSocket connection failed. Check the Python server.');
        socket.onclose = () => { ready=false; stopCapture(); status('Session closed'); $('new').hidden=false; };
        frameTimer = setInterval(captureFrame,3000);
    } catch (exc) { status('Could not start sweep'); error(exc); stopCapture(); $('start').disabled=false; if(playback) await playback.close(); }
};
$('finish').onclick = () => { flushAudio(); command('pause_audio'); command('finish'); stopCapture(); status('Preparing report…'); };
$('new').onclick=()=>location.reload();
window.addEventListener('beforeunload',()=>{ microphone?.getTracks().forEach(t=>t.stop());camera?.getTracks().forEach(t=>t.stop());socket?.close(); });

if (!backendBase) {
    $('start').disabled = true;
    status('Live service is not connected yet.');
    if (!$('errors').textContent) {
        error('The site owner needs to connect the hosted live service before starting a sweep.');
    }
}
