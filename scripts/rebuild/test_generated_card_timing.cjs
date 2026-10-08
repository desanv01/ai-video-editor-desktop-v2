'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const[repoArg,outArg,modulesArg]=process.argv.slice(2),repo=path.resolve(repoArg),out=path.resolve(outArg),modules=path.resolve(modulesArg||path.join(repo,'desktop/node_modules'));
fs.mkdirSync(out,{recursive:false});const desktop=Module.createRequire(path.join(modules,'../package.json')),esbuild=desktop('esbuild');
const component=path.join(repo,'desktop/src/components/GuidedWorkflow.tsx');
const production=fs.readFileSync(component,'utf8')+'\nexport { createEducationalOverlaysFromChapters as acceptanceGenerator };\n';
const compiled=esbuild.buildSync({stdin:{contents:production,resolveDir:path.dirname(component),sourcefile:component,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',packages:'external',nodePaths:[modules]}).outputFiles[0].text;
const filename=path.join(out,'production-generator.cjs');fs.writeFileSync(filename,compiled);const runtime=new Module(filename,module);runtime.filename=filename;runtime.paths=[modules,...Module._nodeModulePaths(out)];runtime._compile(compiled,filename);
const generate=runtime.exports.acceptanceGenerator,cases=[],chapter=(timestamp,label)=>({timestamp,label,formatted:'00:00',keywords:['remote','bridge']});
function test(name,fn){try{fn();cases.push({name,status:'passed'});}catch(e){cases.push({name,status:'failed',error:String(e)});}console.log(cases.at(-1).status+' '+name);}
function validate(chapters,duration){const overlays=generate(chapters,duration),cards=overlays.filter(x=>['intro_card','section_title_card'].includes(x.overlay_type)).sort((a,b)=>a.start_time-b.start_time);for(const x of overlays){assert.ok(Number.isFinite(x.start_time)&&Number.isFinite(x.end_time));assert.ok(x.start_time>=0&&x.end_time<=duration&&x.end_time>x.start_time,'Generated overlay must fit actual lecture');}for(let i=1;i<cards.length;i++)assert.ok(cards[i].start_time>=cards[i-1].end_time,'Generated centered cards overlap');return overlays;}
test('first-zero-chapter-does-not-duplicate-centered-intro',()=>{const o=validate([chapter(0,'Remote and device')],36.5);assert.equal(o.filter(x=>x.overlay_type==='intro_card').length,1);assert.ok(o.some(x=>x.overlay_type==='chapter_label'&&x.title==='Remote and device'));});
test('adjacent-short-chapters-fit-without-centered-collisions',()=>{validate([chapter(0,'A'),chapter(2,'B'),chapter(3,'C')],4);});
test('final-chapter-overlays-do-not-exceed-end',()=>{validate([chapter(0,'A'),chapter(9.5,'B')],10);});
test('late-first-chapter-keeps-distinct-intro-and-section',()=>{const o=validate([chapter(10,'A'),chapter(20,'B')],30);assert.ok(o.some(x=>x.overlay_type==='section_title_card'&&x.title==='A'));});
test('sub-half-second-lecture-has-no-invalid-generated-duration',()=>{validate([chapter(0,'Short')],0.3);});
const receipt={status:cases.every(x=>x.status==='passed')?'passed':'failed',scope:'Actual production TypeScript chapter-overlay generator bundled with unchanged imports and a test-only export; no generator implementation mirror, backend/provider/profile changes.',cases};fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));process.exitCode=receipt.status==='passed'?0:1;
