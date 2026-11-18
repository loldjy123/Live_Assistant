const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync(require('path').join(__dirname, '../index.html'), 'utf8');
const startup = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
function check(address) {
    const result = {panels: [], scripts: []};
    const element = tag => ({tag, children: [], append(...children) {this.children.push(...children);}});
    const url = new URL(address);
    vm.runInNewContext(startup, {
        URL,
        location: url,
        document: {
            baseURI: address,
            createElement: element,
            querySelector() {return {replaceChildren(panel) {result.panels.push(panel);}};},
            body: {append(script) {result.scripts.push(script.src);}},
        },
    });
    return result;
}
assert.equal(check('file:///project/index.html').panels.length, 1);
assert.deepEqual(check('https://loldjy123.github.io/Live_Assistant/').scripts,
    ['https://loldjy123.github.io/Live_Assistant/app.js']);
assert.deepEqual(check('https://assistant.example.com/').scripts,
    ['https://assistant.example.com/app.js']);
console.log('Startup checks passed for local file, GitHub Pages subpath and hosted website.');
