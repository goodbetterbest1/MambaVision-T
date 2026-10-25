(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const els = {
    list: $('#imageList'), search: $('#searchInput'), image: $('#panorama'), stage: $('#imageStage'), viewport: $('#canvasViewport'), canvas: $('#overlay'), empty: $('#emptyState'),
    saveStatus: $('#saveStatus'), saveBtn: $('#saveBtn'), annotator: $('#annotatorId'), quality: $('#imageQuality'), grade: $('#caseGrade'), review: $('#reviewStatus'),
    pointJaw: $('#pointJaw'), pointSeverity: $('#pointSeverity'), pointConfidence: $('#pointConfidence'), pointList: $('#pointList'), pointCount: $('#pointCount'), notes: $('#notes'),
    explanationEnabled: $('#explanationEnabled'), explanationFields: $('#explanationFields'), finding: $('#finding'), evidence: $('#evidence'), desired: $('#desiredExplanation'), uncertainty: $('#uncertainty'),
    evidencePreview: $('#evidencePreview'), toolHint: $('#toolHint'), zoomLabel: $('#zoomLabel'), toast: $('#toast'),
  };
  const ctx = els.canvas.getContext('2d');
  const state = { images: [], index: -1, current: null, tool: 'view', dirty: false, saving: false, saveTimer: null, saveSeq: 0, savePromise: null, editRevision: 0, loading: false, loadSeq: 0, zoom: 1, publicPolygons: [], filter: 'all', selectedPoint: null, draftLine: null, toastTimer: null };
  const labels = { mild: '轻度', moderate: '中度', severe: '重度', none: '未见明显吸收', uncertain: '不确定', ungradable: '不可评估', upper: '上颌', lower: '下颌', unknown: '不确定' };
  const colors = { upper: '#91dac4', lower: '#83b7f4', mild: '#91dac4', moderate: '#f0c36d', severe: '#ef8a78', none: '#aab4b0', uncertain: '#c294e8', ungradable: '#85939a' };
  let toastTimeout;

  function escapeHtml(text) { return String(text ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function toast(message, error = false) { els.toast.textContent = message; els.toast.classList.toggle('error', error); els.toast.classList.add('show'); clearTimeout(toastTimeout); toastTimeout = setTimeout(() => els.toast.classList.remove('show'), 2400); }
  function setStatus(kind, text) { els.saveStatus.className = `save-status ${kind || ''}`; els.saveStatus.lastChild.textContent = text; }
  function currentImage() { return state.images[state.index] || null; }
  function emptyCase(image) { return {schema_version:'dent-alveolar-annotation-v2',image_id:image.image_id,filename:image.filename,width:image.width,height:image.height,modality:'panoramic',image_quality:'unknown',case_grade:'unreviewed',review_status:'in_progress',annotator_id:localStorage.getItem('dental-annotator-id')||'',annotation_version:0,upper_crest_segments:[],lower_crest_segments:[],severity_points:[],notes:'',explanation_sample:{enabled:false,finding:'',evidence:'',desired_explanation:'',uncertainty:'',review_status:'pending'}}; }

  async function request(url, options={}) { const response = await fetch(url, options); const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null; if (!response.ok) throw new Error(data?.error || `HTTP ${response.status}`); return data; }

  function showStorage(storage) {
    if(!storage)return;
    const info=$('#storageInfo');
    info.textContent=`自动保存至本机 · SQLite：${storage.database_path} · JSON：${storage.json_directory}`;
    info.classList.toggle('warning',!!storage.snapshot_warning);
    info.title=storage.snapshot_warning||'数据库为主记录；每次保存同时更新对应影像的本机 JSON 文件。';
    if(storage.snapshot_warning)toast('数据库已保存，但 JSON 镜像写入失败。请检查磁盘空间/目录权限。',true);
  }

  async function loadImages() {
    if (!(await flushChanges())) return;
    setStatus('', '扫描影像…');
    try {
      const data = await request('/api/images'); state.images = data.images;showStorage(data.storage);
      if(data.image_errors?.length)toast(`有 ${data.image_errors.length} 张图片无法读取尺寸，已跳过。请使用 PNG/JPEG 或安装 Pillow 后刷新。`,true);
      if (!state.images.length) { state.index = -1; state.current = null; renderList(); renderCurrent(); setStatus('', '尚未保存'); return; }
      const oldId = state.current?.image_id;
      state.index = Math.max(0, state.images.findIndex((item) => item.image_id === oldId));
      if (oldId && state.index === 0 && state.images[0].image_id !== oldId) state.index = 0;
      renderList(); await loadCurrent();
    } catch (error) { toast(`读取影像失败：${error.message}`, true); setStatus('error', '读取失败'); }
  }

  function renderList() {
    const query = els.search.value.trim().toLowerCase();
    const visible = state.images.map((image, index) => ({image,index})).filter(({image}) => {
      const matches = image.filename.toLowerCase().includes(query);
      const filter = state.filter === 'all' || (state.filter === 'todo' && image.review_status !== 'complete') || (state.filter === 'complete' && image.review_status === 'complete');
      return matches && filter;
    });
    $('#queueSummary').textContent = `${state.images.length} 张影像 · 自动保存到本机`;
    $('#countAll').textContent = state.images.length;
    $('#countTodo').textContent = state.images.filter((item) => item.review_status !== 'complete').length;
    $('#countComplete').textContent = state.images.filter((item) => item.review_status === 'complete').length;
    if (!visible.length) { els.list.innerHTML = '<div class="muted-empty">没有匹配的影像</div>'; return; }
    els.list.innerHTML = visible.map(({image,index}) => `<button class="image-item ${index===state.index?'active':''}" data-index="${index}"><img class="thumb" src="${image.url}" loading="lazy" alt=""><span class="image-item-info"><span class="image-item-name">${escapeHtml(image.filename)}</span><span class="image-item-sub"><i class="state-dot ${image.review_status==='complete'?'done':''}"></i>${image.saved? (image.review_status==='complete'?'已完成':'已保存'):'待标注'} · ${image.width}×${image.height}</span></span></button>`).join('');
    els.list.querySelectorAll('.image-item').forEach((button) => button.addEventListener('click', () => selectImage(Number(button.dataset.index))));
  }

  async function selectImage(index) {
    if (state.loading || index < 0 || index >= state.images.length || index === state.index) return;
    if (!(await flushChanges())) return;
    state.index = index; await loadCurrent();
  }

  async function loadCurrent() {
    const image = currentImage();
    if (!image) { state.current=null; renderCurrent(); return; }
    const loadId = ++state.loadSeq;
    state.loading = true;
    try {
      const result = await request(`/api/annotations/${encodeURIComponent(image.image_id)}`);
      if (loadId !== state.loadSeq) return;
      state.current = result.case; state.publicPolygons = result.public_polygons || [];
      state.dirty = false; state.selectedPoint = null; state.zoom = 1;
      els.image.onload = () => { fitImage(); drawOverlay(); };
      els.image.onerror = () => toast('浏览器无法解码此影像格式，请转换为 PNG 或 JPEG。', true);
      els.image.src = image.url;
      syncForm(); renderCurrent(); renderList(); setStatus(state.current.annotation_version ? 'saved' : '', state.current.annotation_version ? '已保存' : '尚未保存');
    } catch (error) {
      state.index = state.images.findIndex(item => item.image_id === state.current?.image_id);
      renderList(); toast(`载入标注失败：${error.message}`, true);
    } finally { if (loadId === state.loadSeq) state.loading = false; }
  }

  function syncForm() {
    const c=state.current; if(!c) return;
    els.annotator.value=c.annotator_id || localStorage.getItem('dental-annotator-id') || '';
    els.quality.value=c.image_quality || 'unknown'; els.grade.value=c.case_grade || 'unreviewed'; els.review.value=c.review_status || 'in_progress';
    els.notes.value=c.notes || ''; els.explanationEnabled.checked=!!c.explanation_sample?.enabled;
    els.finding.value=c.explanation_sample?.finding||''; els.evidence.value=c.explanation_sample?.evidence||''; els.desired.value=c.explanation_sample?.desired_explanation||''; els.uncertainty.value=c.explanation_sample?.uncertainty||'';
    els.explanationFields.classList.toggle('hidden',!els.explanationEnabled.checked);
    renderPointList(); updateEvidence();
  }

  function renderCurrent() {
    const image=currentImage();
    if(!image){els.stage.classList.remove('visible');els.empty.classList.remove('hidden');$('#imageName').textContent='请先将影像放入 data/images';$('#imageMeta').textContent='支持 JPG、PNG、WEBP、TIFF、BMP';$('#positionLabel').textContent='0 / 0';drawOverlay();return;}
    $('#imageName').textContent=image.filename;$('#imageMeta').textContent=`${image.width} × ${image.height} px · ${(image.bytes/1024/1024).toFixed(2)} MB`;
    $('#positionLabel').textContent=`${state.index+1} / ${state.images.length}`;els.empty.classList.add('hidden');els.stage.classList.add('visible');
    updateTool();drawOverlay();
  }

  function fitImage() {
    if(!state.current || !els.image.naturalWidth) return;
    const rect=els.viewport.getBoundingClientRect(); const maxW=Math.max(80,rect.width-36), maxH=Math.max(80,rect.height-32);
    const fit=Math.min(maxW/els.image.naturalWidth,maxH/els.image.naturalHeight,1); const width=Math.round(els.image.naturalWidth*fit*state.zoom),height=Math.round(els.image.naturalHeight*fit*state.zoom);
    els.image.style.width=`${width}px`;els.image.style.height=`${height}px`;els.stage.style.width=`${width}px`;els.stage.style.height=`${height}px`;
    if(els.canvas.width!==els.image.naturalWidth)els.canvas.width=els.image.naturalWidth;if(els.canvas.height!==els.image.naturalHeight)els.canvas.height=els.image.naturalHeight;
    els.zoomLabel.textContent=`${Math.round(state.zoom*100)}%`;drawOverlay();
  }

  function drawPolyline(line,color,width=5,dashed=false) {
    if(!line || line.length<1) return;
    ctx.save();ctx.lineWidth=width;ctx.strokeStyle=color;ctx.lineJoin='round';ctx.lineCap='round';if(dashed)ctx.setLineDash([10,8]);
    ctx.beginPath();ctx.moveTo(line[0][0]*els.canvas.width,line[0][1]*els.canvas.height);
    for(let i=1;i<line.length;i++)ctx.lineTo(line[i][0]*els.canvas.width,line[i][1]*els.canvas.height);
    if(line.length===1){ctx.lineTo(line[0][0]*els.canvas.width+1,line[0][1]*els.canvas.height+1);}ctx.stroke();
    for(const [x,y] of line){ctx.beginPath();ctx.fillStyle=color;ctx.arc(x*els.canvas.width,y*els.canvas.height,Math.max(2.5,width*.65),0,Math.PI*2);ctx.fill();}
    ctx.restore();
  }
  function drawPolygons() {
    const sx=els.canvas.width/(state.current?.width||1),sy=els.canvas.height/(state.current?.height||1);
    ctx.save();ctx.strokeStyle='#f2d980';ctx.fillStyle='#f2d98022';ctx.lineWidth=2;ctx.setLineDash([8,6]);
    for(const item of state.publicPolygons){for(const segmentation of item.segmentation||[]){if(!Array.isArray(segmentation)||segmentation.length<6)continue;ctx.beginPath();ctx.moveTo(segmentation[0]*sx,segmentation[1]*sy);for(let i=2;i+1<segmentation.length;i+=2)ctx.lineTo(segmentation[i]*sx,segmentation[i+1]*sy);ctx.closePath();ctx.fill();ctx.stroke();}}
    ctx.restore();
  }
  function drawPoints() {
    const points=state.current?.severity_points||[];const w=els.canvas.width,h=els.canvas.height;
    points.forEach((point,index)=>{const x=point.x*w,y=point.y*h,color=colors[point.severity]||colors.uncertain;ctx.save();ctx.beginPath();ctx.fillStyle='#111a';ctx.arc(x,y,15,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.fillStyle=color;ctx.arc(x,y,10,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#111';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#17201e';ctx.font='bold 10px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(index+1),x,y);ctx.restore();});
  }
  function drawOverlay() {
    if(!ctx || !els.canvas.width) return;ctx.clearRect(0,0,els.canvas.width,els.canvas.height);
    if($('#showPublic').checked)drawPolygons();
    if(state.current){(state.current.upper_crest_segments||[]).forEach(segment=>drawPolyline(segment,colors.upper,Math.max(4,els.canvas.width/600)));(state.current.lower_crest_segments||[]).forEach(segment=>drawPolyline(segment,colors.lower,Math.max(4,els.canvas.width/600)));drawPoints();}
    if(state.draftLine)drawPolyline(state.draftLine.points,state.draftLine.type==='upper'?colors.upper:colors.lower,Math.max(4,els.canvas.width/600),true);
  }

  function updateTool() {
    document.querySelectorAll('.tool').forEach((button)=>button.classList.toggle('active',button.dataset.tool===state.tool));
    els.stage.classList.remove('draw-upper','draw-lower','draw-point'); if(['upper','lower','point'].includes(state.tool))els.stage.classList.add(`draw-${state.tool}`);
    const hints={view:'浏览模式：检查影像与标注。',upper:'上颌线：按住鼠标左键沿可见牙槽嵴绘制；在采样稀疏区域补点。',lower:'下颌线：按住鼠标左键沿可见牙槽嵴绘制。',point:'严重度点：先在右侧选择颌别与等级，再点击影像添加位置点。'};els.toolHint.textContent=hints[state.tool];
  }

  function markDirty() { if(!state.current || state.loading)return;state.editRevision+=1;state.dirty=true;setStatus('saving','有未保存修改');updateEvidence();clearTimeout(state.saveTimer);state.saveTimer=setTimeout(saveCurrent,750); }
  function collectForm() {
    return {...state.current,annotator_id:els.annotator.value.trim(),image_quality:els.quality.value,case_grade:els.grade.value,review_status:els.review.value,notes:els.notes.value,explanation_sample:{enabled:els.explanationEnabled.checked,finding:els.finding.value,evidence:els.evidence.value,desired_explanation:els.desired.value,uncertainty:els.uncertainty.value,review_status:'pending'}};
  }
  async function saveCurrent() {
    if(state.savePromise) return state.savePromise;
    if(!state.current || !state.dirty) return true;
    clearTimeout(state.saveTimer);
    state.saving=true;setStatus('saving','保存中…');
    const revision=state.editRevision;
    const imageId=state.current.image_id;
    // Freeze nested points/segments: drawing while a request is in flight must not mutate its snapshot.
    const payload=JSON.parse(JSON.stringify(collectForm()));
    state.savePromise=(async()=>{
      let success=false;
      try{
        const response=await request(`/api/annotations/${encodeURIComponent(imageId)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if(state.current?.image_id===imageId){
          const changed=state.editRevision!==revision;
          // Preserve newer geometry and form edits instead of replacing them with an older server response.
          state.current=changed?{...state.current,annotation_version:response.case.annotation_version,created_at:response.case.created_at,updated_at:response.case.updated_at}:response.case;
          state.dirty=changed;
          state.images=state.images.map(item=>item.image_id===imageId?{...item,saved:true,review_status:response.case.review_status,case_grade:response.case.case_grade}:item);
          setStatus(changed?'saving':'saved',changed?'有新修改待保存':'已保存');updateEvidence();renderList();
        }
        showStorage(response.storage);
        success=true;
      }catch(error){setStatus('error','保存失败');toast(`保存失败：${error.message}；修改仍保留在页面中。`,true);}
      finally{
        state.saving=false;state.savePromise=null;
        // Retry only newer edits after a successful save, never loop indefinitely on a failed request.
        if(success&&state.dirty&&state.current?.image_id===imageId)state.saveTimer=setTimeout(saveCurrent,500);
      }
      return success;
    })();
    return state.savePromise;
  }

  async function flushChanges() {
    if(state.draftLine){toast('请先结束当前笔画。',true);return false;}
    while(state.dirty || state.savePromise){if(!(await saveCurrent()))return false;}
    return true;
  }

  function renderPointList() {
    const points=state.current?.severity_points||[];els.pointCount.textContent=String(points.length);
    if(!points.length){els.pointList.innerHTML='<div class="muted-empty">尚未添加位置点</div>';return;}
    els.pointList.innerHTML=points.map((p,index)=>`<div class="point-row"><span class="point-badge">${index+1}</span><span class="point-details"><strong>${labels[p.jaw]||'不确定'} · ${labels[p.severity]||p.severity}</strong><small>x ${(p.x*100).toFixed(1)}% · y ${(p.y*100).toFixed(1)}% · ${p.confidence||'unknown'}</small></span><button class="point-remove" data-point-id="${escapeHtml(p.id)}" title="删除此点">×</button></div>`).join('');
    els.pointList.querySelectorAll('.point-remove').forEach((button)=>button.addEventListener('click',()=>{state.current.severity_points=state.current.severity_points.filter((p)=>p.id!==button.dataset.pointId);state.selectedPoint=null;renderPointList();drawOverlay();markDirty();}));
  }

  function evidenceObject() {
    if(!state.current)return null;const c=collectForm();const lineSummary=(segments)=>({n_segments:segments.length,n_points:segments.reduce((n,line)=>n+line.length,0),segments:segments.map(line=>({start:line[0],end:line[line.length-1],n_points:line.length}))});
    const counts={none:0,mild:0,moderate:0,severe:0,uncertain:0,ungradable:0};c.severity_points.forEach((p)=>counts[p.severity]=(counts[p.severity]||0)+1);
    return {schema_version:'dent-alveolar-evidence-v1',image_id:c.image_id,filename:c.filename,image_quality:c.image_quality,case_grade:c.case_grade,review_status:c.review_status,crest_lines:{upper:lineSummary(c.upper_crest_segments),lower:lineSummary(c.lower_crest_segments)},severity_counts:counts,severity_points:c.severity_points,limitations:['证据来自人工标注，不等同于临床诊断。','未提供 CEJ、根尖和经验证测量时，不输出标准化 RBL 百分比。','解释应引用可见证据并说明不确定性，不生成隐藏推理过程。']};
  }
  function updateEvidence() { const value=evidenceObject();els.evidencePreview.textContent=value?JSON.stringify(value,null,2):'尚无可用标注'; }

  function pointerPosition(event) { const rect=els.canvas.getBoundingClientRect();return [Math.min(1,Math.max(0,(event.clientX-rect.left)/rect.width)),Math.min(1,Math.max(0,(event.clientY-rect.top)/rect.height))]; }
  els.canvas.addEventListener('pointerdown',(event)=>{if(!state.current || state.loading || event.button!==0)return;if(state.tool==='point'){const [x,y]=pointerPosition(event);state.current.severity_points.push({id:`p${Date.now()}${Math.floor(Math.random()*1000)}`,x,y,jaw:els.pointJaw.value,severity:els.pointSeverity.value,confidence:els.pointConfidence.value,note:''});renderPointList();drawOverlay();markDirty();return;}if(state.tool==='upper'||state.tool==='lower'){event.preventDefault();els.canvas.setPointerCapture(event.pointerId);const [x,y]=pointerPosition(event);state.draftLine={type:state.tool,points:[[x,y]]};drawOverlay();}});
  els.canvas.addEventListener('pointermove',(event)=>{if(!state.draftLine)return;const [x,y]=pointerPosition(event);const last=state.draftLine.points.at(-1);const dx=(x-last[0])*els.canvas.width,dy=(y-last[1])*els.canvas.height;if(Math.hypot(dx,dy)>Math.max(3,els.canvas.width/1200)){state.draftLine.points.push([x,y]);drawOverlay();}});
  function finishLine(){if(!state.draftLine)return;const line=state.draftLine;state.draftLine=null;if(line.points.length<2){drawOverlay();return;}state.current[line.type==='upper'?'upper_crest_segments':'lower_crest_segments'].push(line.points);drawOverlay();markDirty();}
  els.canvas.addEventListener('pointerup',finishLine);els.canvas.addEventListener('pointercancel',finishLine);

  function bindField(element, event='change') { element.addEventListener(event,()=>{if(element===els.annotator){localStorage.setItem('dental-annotator-id',element.value.trim());}if(element===els.explanationEnabled)els.explanationFields.classList.toggle('hidden',!element.checked);markDirty();}); }
  [els.annotator,els.quality,els.grade,els.review,els.notes,els.explanationEnabled,els.finding,els.evidence,els.desired,els.uncertainty].forEach((element)=>bindField(element,element.tagName==='TEXTAREA'||element===els.annotator?'input':'change'));
  document.querySelectorAll('.tool').forEach((button)=>button.addEventListener('click',()=>{state.tool=button.dataset.tool;updateTool();}));
  document.querySelectorAll('.filter').forEach((button)=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;document.querySelectorAll('.filter').forEach((b)=>b.classList.toggle('active',b===button));renderList();}));
  els.search.addEventListener('input',renderList);$('#showPublic').addEventListener('change',drawOverlay);$('#refreshBtn').addEventListener('click',async()=>{try{if(!(await flushChanges()))return;await request('/api/refresh',{method:'POST'});await loadImages();}catch(error){toast(`刷新失败：${error.message}`,true);}});
  $('#prevBtn').addEventListener('click',()=>selectImage(state.index-1));$('#nextBtn').addEventListener('click',()=>selectImage(state.index+1));
  $('#zoomIn').addEventListener('click',()=>{state.zoom=Math.min(3,state.zoom*1.2);fitImage();});$('#zoomOut').addEventListener('click',()=>{state.zoom=Math.max(.35,state.zoom/1.2);fitImage();});$('#fitBtn').addEventListener('click',()=>{state.zoom=1;fitImage();});
  els.saveBtn.addEventListener('click',flushChanges);
  $('#undoBtn').addEventListener('click',()=>{if(!state.current)return;if(state.tool==='upper')state.current.upper_crest_segments.pop();else if(state.tool==='lower')state.current.lower_crest_segments.pop();else if(state.current.severity_points.length){state.current.severity_points.pop();renderPointList();}else if(state.current.lower_crest_segments.length)state.current.lower_crest_segments.pop();else state.current.upper_crest_segments.pop();drawOverlay();markDirty();});
  $('#clearBtn').addEventListener('click',()=>{if(!state.current)return;if(state.tool==='upper')state.current.upper_crest_segments=[];else if(state.tool==='lower')state.current.lower_crest_segments=[];else if(state.tool==='point'){state.current.severity_points=[];renderPointList();}else{state.current.upper_crest_segments=[];state.current.lower_crest_segments=[];}drawOverlay();markDirty();});
  document.querySelectorAll('#exportMenu a').forEach(link=>link.addEventListener('click',async event=>{event.preventDefault();if(await flushChanges()){window.location.assign(link.href);$('#exportMenu').classList.add('hidden');}}));
  $('#exportBtn').addEventListener('click',()=>$('#exportMenu').classList.toggle('hidden'));document.addEventListener('click',(event)=>{if(!event.target.closest('.export-menu'))$('#exportMenu').classList.add('hidden');});
  $('#importBtn').addEventListener('click',()=>$('#importFile').click());$('#importFile').addEventListener('change',async(event)=>{const file=event.target.files[0];if(!file)return;try{if(!(await flushChanges()))return;const payload=JSON.parse(await file.text());const result=await request('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload,strategy:$('#importStrategy').value})});toast(`导入完成：${result.imported} 条，已跳过 ${result.skipped + (result.skipped_unknown || 0)} 条`);await loadImages();}catch(error){toast(`导入失败：${error.message}`,true);}finally{event.target.value='';}});
  $('#copyEvidence').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(evidenceObject(),null,2));toast('证据 JSON 已复制');}catch{toast('复制失败，请手动选择预览内容',true);}});
  document.addEventListener('keydown',(event)=>{const tag=document.activeElement?.tagName;if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='s'){event.preventDefault();flushChanges();return;}if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT')return;if(event.key==='ArrowLeft')selectImage(state.index-1);if(event.key==='ArrowRight')selectImage(state.index+1);if(event.key==='/'){event.preventDefault();els.search.focus();}});
  new ResizeObserver(()=>fitImage()).observe(els.viewport);
  window.addEventListener('beforeunload',(event)=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
  loadImages();
})();
