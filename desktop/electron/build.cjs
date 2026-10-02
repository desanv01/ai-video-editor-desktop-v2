const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
fs.copyFileSync(path.join(__dirname, 'package.json'), path.join(root, 'dist-electron', 'package.json'));
