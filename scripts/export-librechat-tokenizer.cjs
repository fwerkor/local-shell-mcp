/* Reproducible BPE differential vectors for pinned LibreChat tokenizer.ts.
 * Prerequisite: js-tiktoken installed externally (not part of WebUI/Worker).
 * NODE_PATH=/path/to/node_modules node scripts/export-librechat-tokenizer.cjs
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { getEncoding } = require('js-tiktoken');
const encoder = getEncoding('o200k_base');
const SPACE = /\s/u;
function boundedTokens(text) {
  let count = 0;
  for (let offset = 0; offset < text.length;) {
    let end = Math.min(offset + 4096, text.length);
    let run = 0;
    let previous = false;
    for (let index = offset; index < end; index++) {
      const whitespace = SPACE.test(text[index]);
      run = whitespace === previous ? run + 1 : 1;
      previous = whitespace;
      if (run >= 256) {
        end = index + 1;
        break;
      }
    }
    const last = text.charCodeAt(end - 1);
    const next = text.charCodeAt(end);
    if (last >= 0xd800 && last <= 0xdbff && next >= 0xdc00 && next <= 0xdfff) {
      end--;
    }
    count += encoder.encode(text.slice(offset, end)).length;
    offset = end;
  }
  return count;
}
let state = 0x9e3779b9;
function random() {
  state ^= state << 13;
  state ^= state >>> 17;
  state ^= state << 5;
  return state >>> 0;
}
const alphabets = ["abCD\t", '好啊语🌍', ' ', '😊😀a', '\r\n', 'مرحبا', '한글', '🧑‍💻🔥', '🙂\u00a0', 'abc 123', '\u2028', 'π∂σ'];
const samples = [
  '', 'hello world', '南京大学', '🌏😎‍💻', 'a'.repeat(300), ' '.repeat(300),
  '👨‍👩‍👧'.repeat(12), 'a '.repeat(2047) + 'a😊', '你好 '.repeat(300),
  '\u0085'.repeat(310), '\uFEFF'.repeat(310), 'A'.repeat(300),
  'a\t'.repeat(350), '\u2000\u2001'.repeat(350), '😊😀 '.repeat(120),
  '您\n好'.repeat(200), '💡 '.repeat(180), 'ab '.repeat(260),
];
for (let index = 0; index < 140; index++) {
  const target = index < 110 ? 20 + random() % 220 : 200 + random() % 650;
  let buffer = '';
  while (buffer.length < target) {
    const abc = [...alphabets[random() % alphabets.length]];
    buffer += abc[random() % abc.length];
  }
  // Iterate Unicode code points, never construct malformed UTF-16 strings.
  samples.push(buffer);
}
const vectors = samples.map(text => ({text, exact: encoder.encode(text).length, bounded: boundedTokens(text)}));
const destination = path.resolve(__dirname, '../tests/fixtures/librechat/tokenizer_vectors.json');
fs.writeFileSync(destination, JSON.stringify({source:'LibreChat packages/api/src/utils/tokenizer.ts e8f3be08 + js-tiktoken o200k_base',vectors}) + '\n');
console.log('Wrote',vectors.length,'vectors',destination);
