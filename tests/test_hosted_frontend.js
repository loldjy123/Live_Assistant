const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]);

function load(address, backendUrl='', health={app:'live-book-inventory',ready:true,websocket_path:'/ws'}) {
    const elements = Object.fromEntries(ids.map(id => [id, {textContent:'', disabled:false, children:[], append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=nodes;}}]));
    let moduleUrl;
    const context = vm.createContext({
        URL,
        AbortSignal: {timeout(){return {};}},
        async fetch(address){
            const result = typeof health === 'function' ? health(String(address)) : health;
            if (result instanceof Error) throw result;
            return {ok:result.httpStatus !== 404, async json(){return result;}};
        },
        location: new URL(address),
        window: {LIBRARY_CONFIG:{backendUrl}, addEventListener(){}},
        document: {
            createElement(tag){return {tag,textContent:'',children:[],append(...nodes){this.children.push(...nodes);}};},
            baseURI:address,
            getElementById(id) {assert(id in elements, `Missing HTML element: ${id}`); return elements[id];},
        },
        AudioContext: class {
            constructor(){this.audioWorklet={addModule:async url=>{moduleUrl=url;}};}
            async resume(){}
        },
        AudioWorkletNode: class {connect(){}},
    });
    vm.runInContext(source, context);
    return {context, elements, module:()=>moduleUrl};
}

(async () => {
    const hosted = load('https://assistant.example.com/');
    vm.runInContext(`renderInventory({
        sweep:{currency:'USD'},
        books:[
            {kind:'book',title:'Known book',status:'identified',stage:'identified'},
            {kind:'book',title:'',status:'unidentified',stage:'identified'},
        ],
        totals:{book_count:2,books_identified:1,books_replacement_cost:0,books_used_value:0},
    })`, hosted.context);
    assert.equal(hosted.elements.inventory.children.length, 1);
    assert(hosted.elements.bookTotals.textContent.includes('1 of 2 detected'));

    assert.equal(vm.runInContext("backendEndpoint('ws').href", hosted.context), 'https://assistant.example.com/ws');
    await vm.runInContext('verifyBackend()', hosted.context);
    const oldServer = load('https://assistant.example.com/', '', {app:'live-book-inventory',ready:true});
    await assert.rejects(vm.runInContext('verifyBackend()', oldServer.context), /older or incompatible/);
    const stopped = load('https://assistant.example.com/', '', new Error('Connection refused'));
    await assert.rejects(vm.runInContext('verifyBackend()', stopped.context), /Cannot reach/);
    const preview = load('http://localhost:63342/live_agent/index.html', '', address =>
        new URL(address).port === '63342' ? {httpStatus:404}
            : {app:'live-book-inventory',ready:true,websocket_path:'/ws'});
    await vm.runInContext('verifyBackend()', preview.context);
    assert.equal(vm.runInContext("backendEndpoint('ws').href", preview.context), 'http://localhost:8080/ws');
    const customLocal = load('http://localhost:9000/');
    await vm.runInContext('verifyBackend()', customLocal.context);
    assert.equal(vm.runInContext("backendEndpoint('ws').href", customLocal.context), 'http://localhost:9000/ws');
    const pages = load('https://loldjy123.github.io/Live_Assistant/', 'https://api.example.com/');
    assert.equal(vm.runInContext("backendEndpoint('/claims/test/report.html').href", pages.context), 'https://api.example.com/claims/test/report.html');
    await vm.runInContext('setupPlayback()', pages.context);
    assert.equal(pages.module(), 'https://loldjy123.github.io/Live_Assistant/processor.js');
    const missing = load('https://loldjy123.github.io/Live_Assistant/');
    assert(missing.elements.start.disabled);
    const insecure = load('https://loldjy123.github.io/Live_Assistant/', 'http://api.example.com/');
    assert(insecure.elements.start.disabled);
    assert(insecure.elements.errors.textContent.includes('HTTPS'));
    console.log('Hosted frontend checks passed: same-origin backend, Pages assets, remote report links and HTTPS validation.');
})().catch(error => {console.error(error);process.exit(1);});
