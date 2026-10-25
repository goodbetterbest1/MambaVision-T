// Dependency-free regression tests for the real browser application's persistence logic.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

function harness() {
  const elements = new Map();
  function element(key) {
    if (!elements.has(key)) elements.set(key, {
      value: '', checked: false, textContent: '', innerHTML: '', lastChild: {textContent:''}, dataset:{},
      classList: {add(){},remove(){},toggle(){}}, addEventListener(){}, querySelectorAll(){return[];},
      getContext(){return{clearRect(){}};}, getBoundingClientRect(){return{width:900,height:500};}
    });
    return elements.get(key);
  }
  const pending=[];
  const timers=[];
  const context={
    document:{querySelector:element,querySelectorAll(){return[];},addEventListener(){}},
    window:{addEventListener(){},location:{assign(){}}},
    navigator:{},localStorage:{getItem(){return'';},setItem(){}},
    ResizeObserver:class{observe(){}},
    setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},
    fetch:async(url,opts)=>{
      if(url==='/api/images')return{ok:true,headers:{get(){return'application/json';}},json:async()=>({images:[]})};
      if(opts?.method==='PUT')return new Promise(resolve=>pending.push({payload:JSON.parse(opts.body),resolve}));
      throw Error('unexpected fetch: '+url);
    },console
  };
  const source=readFileSync(join(__dirname,'../web/app.js'),'utf8');
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'window.testHooks={state,saveCurrent,flushChanges,markDirty,collectForm};})();'),context);
  return {hooks:context.window.testHooks,pending,timers,elements};
}
function caseRecord() {
  return {image_id:'demo',filename:'demo.png',width:1000,height:500,upper_crest_segments:[],lower_crest_segments:[],severity_points:[],annotation_version:0,explanation_sample:{}};
}
async function prepare() {
  const h=harness();
  // Let the initial empty image listing finish before installing the synthetic case.
  await new Promise(resolve=>setImmediate(resolve));
  h.hooks.state.current=caseRecord();
  h.hooks.state.images=[{image_id:'demo',filename:'demo.png',width:1000,height:500,saved:false}];
  h.elements.get('#imageQuality').value='good';
  h.elements.get('#caseGrade').value='moderate';
  h.elements.get('#reviewStatus').value='in_progress';
  return h;
}
function succeed(request) {
  const saved={...request.payload,annotation_version:1,created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'};
  request.resolve({ok:true,headers:{get(){return'application/json';}},json:async()=>({case:saved})});
}
test('normal save clears dirty state and updates queue',async()=>{
  const h=await prepare();h.hooks.markDirty();const save=h.hooks.saveCurrent();
  assert.equal(h.pending.length,1);succeed(h.pending[0]);assert.equal(await save,true);
  assert.equal(h.hooks.state.dirty,false);assert.equal(h.hooks.state.images[0].saved,true);
});
test('new geometry during an in-flight save survives the old response',async()=>{
  const h=await prepare();h.hooks.markDirty();const save=h.hooks.saveCurrent();
  h.hooks.state.current.upper_crest_segments.push([[.1,.2],[.3,.4]]);h.hooks.markDirty();
  assert.equal(h.pending[0].payload.upper_crest_segments.length,0);
  succeed(h.pending[0]);await save;
  assert.equal(h.hooks.state.current.upper_crest_segments.length,1);
  assert.equal(h.hooks.state.dirty,true);
  const second=h.hooks.saveCurrent();succeed(h.pending[1]);await second;
  assert.equal(h.pending[1].payload.upper_crest_segments.length,1);assert.equal(h.hooks.state.dirty,false);
});
test('failed save preserves unsaved edits and does not auto-retry forever',async()=>{
  const h=await prepare();h.hooks.markDirty();const count=h.timers.length;const save=h.hooks.saveCurrent();
  h.pending[0].resolve({ok:false,status:500,headers:{get(){return'application/json';}},json:async()=>({error:'test failure'})});
  assert.equal(await save,false);assert.equal(h.hooks.state.dirty,true);
  // Failure toast schedules its hide timer; no persistence retry is scheduled.
  assert.equal(h.timers.length,count+1);
});
test('flush refuses navigation/export during an unfinished stroke',async()=>{
  const h=await prepare();h.hooks.state.draftLine={type:'upper',points:[[.1,.2]]};
  assert.equal(await h.hooks.flushChanges(),false);assert.equal(h.pending.length,0);
});
