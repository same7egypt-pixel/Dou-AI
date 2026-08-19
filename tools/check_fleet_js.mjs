import fs from 'node:fs';

const html = fs.readFileSync('/home/ubuntu/dou-server/static/fleet.html', 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(match => match[1]);
if (!scripts.length) throw new Error('No inline scripts found in fleet.html');
fs.writeFileSync('/tmp/fleet-inline.js', scripts.join('\n\n'));
