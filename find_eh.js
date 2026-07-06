let fs = require('fs');
let bot = fs.readFileSync('C:/Users/13249/Documents/Codex/2026-07-05/tb-deploy/bot.py', 'utf8');

// Find _send_eh_detail and get exact content
let idx = bot.indexOf('async def _send_eh_detail(update, url, publish_date=""):');
if (idx < 0) {
    console.log('New signature NOT FOUND, checking old');
    idx = bot.indexOf('async def _send_eh_detail(update, url):');
}
if (idx < 0) {
    console.log('_send_eh_detail NOT FOUND at all');
    process.exit(1);
}

let snippet = bot.substring(idx, idx + 800);
console.log(snippet);
