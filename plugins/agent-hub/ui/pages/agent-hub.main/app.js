(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const identity = {pluginId: params.get('pluginId') || 'stella.agent-hub', pageId: params.get('pageId') || 'agent-hub.main', channelNonce: params.get('channelNonce') || '', generation: Number(params.get('generation') || 0)};
  const tokens = ['--bg-base','--bg-surface','--bg-surface-2','--bg-inset','--text-primary','--text-secondary','--text-tertiary','--border-default','--accent','--accent-soft','--accent-contrast'];
  const labels = {draft:'草稿',ready:'待执行',pending:'待执行',queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancel_requested:'正在取消',cancelled:'已取消',outcome_unknown:'结果未知',waiting_approval:'等待审批',interrupted:'已中断'};
  let task = null, tasks = [], providers = [], natives = [], tab = 'flow', selectedStep = '', selectedExecution = '', activity = [], activityCursor = 0, activitySnapshot = null, loadGeneration = 0, busy = false, polling = false, workflowDraft = [], workflowRevision = 0;
  const drafts = new Map(), reads = new Map(), pending = new Map(), personDrafts = new Map();
  const state = step => step.attempts.length ? step.attempts.at(-1).status : 'pending';
  const name = id => task?.participants.find(p => p.participantId === id)?.displayName || '用户';
  function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; }
  function button(text, action, cls) { const el = node('button', text, cls); el.type = 'button'; el.addEventListener('click', () => guard(action)); return el; }
  function notice(text) { $('notice').textContent = text; }
  async function guard(action) { try { await action(); } catch (err) { notice(err.message || String(err)); } }
  function invoke(method, input = {}) {
    if (window.parent === window) return Promise.reject(new Error('请从 Stella 打开此页面'));
    const requestId = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(requestId); reject(new Error('连接超时，请刷新后重试')); }, 125000);
      pending.set(requestId, {resolve, reject, timer});
      window.parent.postMessage({type:'stella-bridge-invoke',requestId,...identity,method,input}, '*');
    });
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    const data = event.data || {};
    if (data.pluginId !== identity.pluginId || data.pageId !== identity.pageId || data.channelNonce !== identity.channelNonce || data.generation !== identity.generation) return;
    if (data.type === 'stella-theme') {
      for (const key of tokens) if (typeof data.tokens?.[key] === 'string' && CSS.supports('color', data.tokens[key])) document.documentElement.style.setProperty(key, data.tokens[key]);
      document.documentElement.style.colorScheme = data.colorScheme === 'dark' ? 'dark' : 'light';
      return;
    }
    if (data.type !== 'stella-bridge-result') return;
    const request = pending.get(data.requestId); if (!request) return;
    pending.delete(data.requestId); clearTimeout(request.timer);
    if (data.ok) request.resolve(data.value); else request.reject(new Error(data.error || '操作失败'));
  });
  window.parent.postMessage({type:'stella-page-ready',...identity}, '*');
  function setBusy(value) { busy = value; for (const id of ['draft','recipient','intent','mention']) $(id).disabled = value || !task; for (const id of ['send','send-run','start','workflow','cancel']) $(id).disabled = value || !task; }
  function renderTasks() {
    $('task-list').replaceChildren();
    if (!tasks.length) $('task-list').append(node('p','暂无任务，点击 ＋ 开始。','muted'));
    for (const row of tasks) {
      const el = button('', () => selectTask(row.taskId), `task-row ${task?.taskId === row.taskId ? 'selected' : ''}`);
      el.append(node('strong',row.title),node('small',labels[row.status] || row.status));
      $('task-list').append(el);
    }
  }
  function isProposal(body) {try {if(body.startsWith('```'))body=body.split('\n').slice(1,-1).join('\n');return Array.isArray(JSON.parse(body)?.steps);}catch{return false;}}
  function renderMessages() {
    const box = $('messages'), bottom = box.scrollHeight - box.scrollTop - box.clientHeight < 70;
    box.replaceChildren();
    if (!task) {
      const empty = node('div',undefined,'empty'); empty.append(node('h2','让合适的 Agent 一起协作'),node('p','创建任务，选择参与者。正式交流留在这里，流程、过程和设定集中在详情面板。','muted'),button('新建任务',openCreate,'primary')); box.append(empty); return;
    }
    if (!task.messages.length) { const empty = node('div',undefined,'empty'); empty.append(node('h2',task.title),node('p',task.goal),node('p','先编辑流程，或发送消息给选定负责人。','muted')); box.append(empty); }
    for (const message of task.messages) {
      const el = node('article',undefined,`message ${message.kind}`);
      el.append(node('small',`${name(message.senderParticipantId)}${message.recipientParticipantIds.length ? ' → ' + message.recipientParticipantIds.map(name).join('、') : ''}`),node('div',message.body,'body'));
      if (message.executionId) {
        el.append(button('查看过程', () => selectProcess(message.stepId, message.executionId)));
        if (message.kind === 'reply' && isProposal(message.body)) el.append(button('采用流程提案', async () => { await mutate('adopt_proposal',{execution_id:message.executionId}); notice('流程提案已采用'); }));
      }
      box.append(el);
    }
    if (bottom) box.scrollTop = box.scrollHeight;
  }
  function render() {
    $('task-title').textContent = task?.title || '一起完成下一件事';
    $('task-meta').textContent = task ? `${labels[task.status] || task.status} · ${task.participants.map(p=>p.displayName).join('、')}` : '选择参与者，分工、交流与交付';
    const recipient = $('recipient').value;
    $('recipient').replaceChildren(new Option('公共交流', ''));
    for (const p of task?.participants || []) $('recipient').add(new Option(`@${p.displayName} · ${p.participantId.slice(-4)}`,p.participantId));
    if ([...$('recipient').options].some(o=>o.value===recipient)) $('recipient').value = recipient;
    $('draft').disabled = !task; setBusy(busy); renderTasks(); renderMessages(); renderPanel();
  }
  async function refreshList() { tasks = await invoke('list_tasks',{limit:100}); renderTasks(); }
  async function selectTask(id) {
    if (task) { drafts.set(task.taskId,{body:$('draft').value,recipient:$('recipient').value,intent:$('intent').value}); reads.set(task.taskId,$('messages').scrollTop); }
    const generation = ++loadGeneration;
    const value = await invoke('refresh_task',{task_id:id});
    if (generation !== loadGeneration) return;
    task = value; selectedStep = ''; selectedExecution = ''; activity = []; activityCursor = 0; activitySnapshot = null;
    render(); const saved = drafts.get(id); $('draft').value = saved?.body || ''; $('recipient').value = saved?.recipient || ''; $('intent').value = saved?.intent || 'message';
    $('messages').scrollTop = reads.get(id) || 0; document.body.dataset.pane = 'chat'; notice('');
  }
  async function mutate(method, values) {
    const id = task.taskId, generation = loadGeneration;
    const value = await invoke(method,{task_id:id,expected_revision:task.revision,request_id:crypto.randomUUID(),...values});
    if (generation === loadGeneration && task?.taskId === id) { task = value; render(); }
    await refreshList(); return value;
  }
  function setTab(value) { tab = value; document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===tab))); renderPanel(); }
  function renderPanel() {
    const panel = $('panel'), scroll = panel.querySelector('.log')?.scrollTop || 0; panel.replaceChildren();
    if (!task) { panel.append(node('p','选择一个任务查看流程、输出与 Agent 设定。','muted')); return; }
    if (tab === 'flow') {
      panel.append(node('h2','任务流程'),node('p','独立步骤并行，前置步骤完成后交接。','muted'));
      if (!task.steps.length) panel.append(button('添加流程',openWorkflow));
      const steps = node('div',undefined,'steps');
      for (const step of task.steps) {
        const el = button('',()=>selectProcess(step.stepId,step.attempts.at(-1)?.executionId || ''),`step ${selectedStep===step.stepId?'selected':''}`);
        el.append(node('strong',step.title),node('span',`${name(step.participantId)} · ${labels[state(step)] || state(step)}`,'muted'),node('span',step.dependsOn.length ? '↑ ' + step.dependsOn.map(id=>task.steps.find(s=>s.stepId===id)?.title || id).join(' ＋ ') : '起始步骤','deps'));
        steps.append(el);
      }
      panel.append(flowDiagram(), steps);
    } else if (tab === 'process') {
      const select = node('select'); select.setAttribute('aria-label','查看执行尝试'); select.add(new Option('选择步骤与执行尝试',''));
      for (const s of task.steps) for (const [i,a] of s.attempts.entries()) select.add(new Option(`${s.title} · ${name(s.participantId)} · 第 ${i+1} 次`,a.executionId));
      select.value = selectedExecution; select.addEventListener('change',()=>guard(()=>selectProcess(task.steps.find(s=>s.attempts.some(a=>a.executionId===select.value))?.stepId || '', select.value))); panel.append(select);
      const step = task.steps.find(s=>s.stepId===selectedStep), attempt = step?.attempts.find(a=>a.executionId===selectedExecution);
      if (attempt) {
        const snap = activitySnapshot || attempt.snapshot, card = node('div',undefined,'card');
        card.append(node('h3',`${name(step.participantId)} · ${labels[attempt.status] || attempt.status}`),node('p',`执行模型：${attempt.actualModel || (snap.modelSelection.mode==='explicit' ? snap.modelSelection.modelId + '（请求值）' : '接入默认（实际模型未知）')}`,'muted'),node('p',`人设快照：${snap.persona || '未设置'}`,'muted'));
        if (attempt.error) card.append(node('p',attempt.error.message || attempt.error.code || '执行失败'));
        panel.append(card);
        if (['failed','cancelled','outcome_unknown'].includes(attempt.status)) panel.append(button('重试此步骤',()=>run({step_id:step.stepId,retry:true})));
      }
      const log = node('div',activity.length ? activity.map(e=>e.safePayload.text || e.safePayload.summary || labels[e.type] || e.type).join('\n') : '尚无过程输出。','log'); log.setAttribute('role','log'); log.setAttribute('aria-label','执行过程输出'); panel.append(log); log.scrollTop=scroll;
    } else {
      panel.append(node('h2','参与 Agents'),node('p','修改对下一次执行生效；当前执行保留原设定。','muted'));
      const coordinator = node('select'); coordinator.setAttribute('aria-label','任务负责人');
      for (const p of task.participants) coordinator.add(new Option(p.displayName, p.participantId));
      coordinator.value = task.coordinatorParticipantId;
      coordinator.addEventListener('change',()=>guard(()=>mutate('set_coordinator',{participant_id:coordinator.value})));
      const cl = node('label','任务负责人'); cl.append(coordinator); panel.append(cl);
      const available = [...natives,...providers.filter(p=>p.enabled && ['codex-cli','claude-code','cursor-cli'].includes(p.providerLocalId))];
      const add = node('select'); add.setAttribute('aria-label','加入参与者'); add.add(new Option('选择要加入的 Agent',''));
      for (const p of available) add.add(new Option(p.displayName,p.nativeAgentId || p.providerConfigId));
      panel.append(add, button('加入任务',async()=>{const p=available.find(p=>(p.nativeAgentId || p.providerConfigId)===add.value);if(!p)throw new Error('请选择参与者');await mutate('add_participant',{participant:p.nativeAgentId?{nativeAgentId:p.nativeAgentId}:{providerConfigId:p.providerConfigId}});}));
      for (const person of task.participants) {
        const form = node('form',undefined,'card'); form.append(node('h3',person.displayName),node('p',person.agentId==='stella'?'Stella · 原生 Agent':providers.find(p=>p.providerConfigId===person.providerConfigId)?.providerLocalId || '外部接入','muted'));
        const draftKey = task.taskId + ':' + person.participantId, saved = personDrafts.get(draftKey) || person;
        const persona = node('textarea'); persona.value = saved.persona; persona.maxLength = 8000; const pl = node('label','任务内人设'); pl.append(persona); form.append(pl);
        const mode = node('select'); mode.add(new Option('使用接入默认','default')); mode.add(new Option('指定模型 ID','explicit')); mode.value = saved.modelSelection.mode; mode.setAttribute('aria-label',`${person.displayName} 模型选择`); form.append(mode);
        const model = node('input'); model.value = saved.modelSelection.modelId || ''; model.placeholder='模型 ID'; model.maxLength=160; model.setAttribute('aria-label',`${person.displayName} 模型 ID`); model.hidden=mode.value!=='explicit'; form.append(model); mode.addEventListener('change',()=>{model.hidden=mode.value!=='explicit';});
        const provider = node('input'); provider.value=saved.modelSelection.providerId || ''; provider.placeholder='模型提供者 ID（可选）'; provider.setAttribute('aria-label',`${person.displayName} 模型提供者`); provider.hidden=person.agentId!=='stella'; form.append(provider);
        form.addEventListener('input',()=>personDrafts.set(draftKey,{persona:persona.value,modelSelection:{mode:mode.value,modelId:model.value,providerId:provider.value}}));
        const save = node('button','保存设定'); save.type='submit'; form.append(save);
        form.addEventListener('submit',event=>{event.preventDefault(); const revision=task.revision; guard(async()=>{save.disabled=true; try { const selection={mode:mode.value,...(mode.value==='explicit'?{modelId:model.value,...(provider.value?{providerId:provider.value}:{})}:{})}; await mutate('update_participant',{participant_id:person.participantId,patch:{persona:persona.value,modelSelection:selection},expected_revision:revision}); personDrafts.delete(draftKey); notice('设定已保存，下次执行生效'); } finally {save.disabled=false;} });}); panel.append(form);
      }
    }
  }

  function flowDiagram() {
    const wrap = node('div',undefined,'flow-diagram');
    if (!task.steps.length) return wrap;
    const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns,'svg');
    const ranks = new Map(), position = new Map(), counts = new Map();
    function rank(s) {if(!ranks.has(s.stepId)) ranks.set(s.stepId,s.dependsOn.length?1+Math.max(...s.dependsOn.map(id=>rank(task.steps.find(v=>v.stepId===id)))):0);return ranks.get(s.stepId);}
    for (const s of task.steps) {const r=rank(s),column=counts.get(r)||0;counts.set(r,column+1);position.set(s.stepId,{x:column*150+8,y:r*78+8});}
    svg.setAttribute('viewBox',`0 0 ${Math.max(...counts.values())*150} ${(Math.max(...ranks.values())+1)*78}`);
    svg.style.width=Math.max(...counts.values())*150+'px';svg.setAttribute('role','img');svg.setAttribute('aria-label','步骤依赖图；下方步骤列表可操作');
    for(const s of task.steps){const p=position.get(s.stepId);for(const id of s.dependsOn){const from=position.get(id),line=document.createElementNS(ns,'path');line.setAttribute('d',`M${from.x+67} ${from.y+50} V${p.y-10} H${p.x+67} V${p.y}`);line.setAttribute('class','flow-edge');svg.append(line);}}
    for(const s of task.steps){const p=position.get(s.stepId),group=document.createElementNS(ns,'g'),rect=document.createElementNS(ns,'rect'),label=document.createElementNS(ns,'text'),status=document.createElementNS(ns,'text');
      rect.setAttribute('x',p.x);rect.setAttribute('y',p.y);rect.setAttribute('width','134');rect.setAttribute('height','50');rect.setAttribute('rx','7');
      label.setAttribute('x',p.x+8);label.setAttribute('y',p.y+20);label.textContent=s.title.length>10?s.title.slice(0,10)+'…':s.title;
      status.setAttribute('x',p.x+8);status.setAttribute('y',p.y+38);status.textContent=labels[state(s)]||state(s);status.setAttribute('class','flow-status');
      const title=document.createElementNS(ns,'title');title.textContent=s.title+' · '+name(s.participantId);group.append(title,rect,label,status);group.style.cursor='pointer';group.addEventListener('click',()=>guard(()=>selectProcess(s.stepId,s.attempts.at(-1)?.executionId || '')));svg.append(group);}
    wrap.append(svg); return wrap;
  }
  async function selectProcess(stepId,eid) { selectedStep=stepId; if(eid!==selectedExecution){selectedExecution=eid;activity=[];activityCursor=0;activitySnapshot=null;} setTab('process'); document.body.dataset.pane='details'; await loadActivity(); }
  async function loadActivity() {
    if(!task || !selectedExecution) return;
    const eid=selectedExecution,id=task.taskId,generation=loadGeneration;
    const value=await invoke('task_activity',{task_id:id,execution_id:eid,after_sequence:activityCursor});
    if(generation!==loadGeneration || eid!==selectedExecution) return;
    const known=new Set(activity.map(e=>e.sequence)); activity.push(...value.events.filter(e=>!known.has(e.sequence))); activity=activity.slice(-600); activityCursor=value.nextSequence; activitySnapshot=value.snapshot; if(tab==='process') renderPanel();
  }
  async function openCreate() {
    [providers,natives]=await Promise.all([invoke('list_providers'),invoke('native_participants')]);
    const options=$('participant-options'); options.replaceChildren();
    const available=[...natives,...providers.filter(p=>p.enabled && ['codex-cli','claude-code','cursor-cli'].includes(p.providerLocalId))];
    for(const person of available){const label=node('label',undefined,'participant-option');const row=node('span',undefined,'check'),check=node('input');check.type='checkbox';check.value=person.nativeAgentId || person.providerConfigId;check.dataset.kind=person.nativeAgentId?'native':'provider';row.append(check,node('span',person.displayName));label.append(row,node('small',person.nativeAgentId?'Stella':person.providerLocalId));options.append(label);}
    if(!available.length) options.append(node('p','暂无可用参与者，请先管理接入。','muted'));
    $('create-error').textContent='';$('create-dialog').showModal();
  }
  function openWorkflow() { if(!task)return; workflowDraft=task.steps.map(s=>({...s,dependsOn:[...s.dependsOn]}));workflowRevision=task.revision;$('workflow-error').textContent='';renderWorkflow();$('workflow-dialog').showModal(); }
  function renderWorkflow() {
    const box=$('workflow-items');box.replaceChildren();
    for(const step of workflowDraft){const el=node('div',undefined,'workflow-item');const title=node('input');title.value=step.title;title.placeholder='步骤目标';title.required=true;title.maxLength=1000;title.setAttribute('aria-label','步骤目标');title.addEventListener('input',()=>step.title=title.value);
      const person=node('select');person.setAttribute('aria-label','步骤执行者');for(const p of task.participants)person.add(new Option(p.displayName,p.participantId));person.value=step.participantId;person.addEventListener('change',()=>step.participantId=person.value);el.append(title,person);
      const deps=node('div',undefined,'dependency-options');for(const other of workflowDraft){if(other===step)continue;const label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=step.dependsOn.includes(other.stepId);check.disabled=Boolean(step.attempts?.length);check.addEventListener('change',()=>step.dependsOn=check.checked?[...step.dependsOn,other.stepId]:step.dependsOn.filter(id=>id!==other.stepId));label.append(check,node('span',other.title || '未命名步骤'));deps.append(label);}el.append(node('small','等待这些步骤完成：'),deps);
      if(step.attempts?.length){title.disabled=true;person.disabled=true;el.append(node('small','已执行步骤保留历史，可继续添加后续步骤。'));}else el.append(button('移除',()=>{workflowDraft=workflowDraft.filter(s=>s!==step);for(const s of workflowDraft)s.dependsOn=s.dependsOn.filter(id=>id!==step.stepId);renderWorkflow();}));box.append(el);}
  }
  async function run(input={}) {const id=task.taskId,generation=loadGeneration;setBusy(true);try{const value=await invoke('start_task',{task_id:id,...input});if(generation===loadGeneration){task=value;render();notice('任务已启动，过程在右侧持续更新');}await refreshList();}finally{setBusy(false);}}
  async function send(execute=false) {
    if(!task || busy) return; const body=$('draft').value.trim();if(!body)return;
    const id=task.taskId,generation=loadGeneration;setBusy(true);
    try {let recipient=$('recipient').value, content=body, intent=$('intent').value;
      if(body.startsWith('@')){const p=task.participants.find(p=>body.startsWith(`@${p.displayName} `));if(p){const same=task.participants.filter(v=>v.displayName===p.displayName);if(same.length>1&&!recipient)throw new Error('存在重名 Agent，请通过 @ 菜单选择接收者');recipient=recipient || p.participantId;content=body.slice(p.displayName.length+2).trim();}}
      if(recipient && /^人设[：:]/.test(content)){intent='persona';content=content.replace(/^人设[：:]\s*/,'');}
      await mutate('post_message',{body:content,recipient_ids:recipient?[recipient]:[],intent});
      if(generation!==loadGeneration)return; $('draft').value='';drafts.delete(id);notice(intent==='persona'?'人设已保存':'消息已发送');
      if(execute && intent==='message'){const step={stepId:crypto.randomUUID(),title:content.slice(0,1000),participantId:recipient || task.coordinatorParticipantId,dependsOn:[],attempts:[]};await mutate('set_workflow',{steps:[...task.steps,step].map(({stepId,title,participantId,dependsOn})=>({stepId,title,participantId,dependsOn}))});await run();}
    }finally{setBusy(false);}
  }
  async function connections() {providers=await invoke('list_providers');const box=$('provider-list');box.replaceChildren();for(const row of providers){const card=node('div',undefined,'card provider');card.append(node('h3',row.displayName),node('p',`${row.providerLocalId} · ${row.lastProbe?.status || '未探测'}`,'muted'));const actions=node('div',undefined,'actions');actions.append(button(row.enabled?'停用':'启用',async()=>{await invoke('upsert_provider',{provider:{...row,enabled:!row.enabled}});await connections();}),button('探测',async()=>{await invoke('probe_provider',{provider_config_id:row.providerConfigId});await connections();}));card.append(actions);box.append(card);}if(!$('connections-dialog').open)$('connections-dialog').showModal();}
  // The opaque iframe forbids native form navigation; submit through Bridge only.
  document.addEventListener('click',event=>{const submitter=event.target.closest('button[type=submit]');if(!submitter?.form)return;event.preventDefault();if(submitter.form.reportValidity())submitter.form.dispatchEvent(new SubmitEvent('submit',{cancelable:true,submitter}));});
  document.querySelectorAll('[data-pane]').forEach(b=>{if(b.tagName==='BUTTON')b.addEventListener('click',()=>document.body.dataset.pane=b.dataset.pane);});
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
  $('new-task').addEventListener('click',()=>guard(openCreate));$('connections').addEventListener('click',()=>guard(connections));$('defaults').addEventListener('click',()=>guard(async()=>{await invoke('ensure_defaults');await connections();}));
  $('create-form').addEventListener('submit',event=>{event.preventDefault();guard(async()=>{const submit=event.submitter;submit.disabled=true;try{const participants=[...$('participant-options').querySelectorAll('input:checked')].map(c=>c.dataset.kind==='native'?{nativeAgentId:c.value}:{providerConfigId:c.value});const value=await invoke('create_task',{payload:{title:$('create-title').value,goal:$('create-goal').value,participants},request_id:crypto.randomUUID()});$('create-dialog').close();$('create-form').reset();await refreshList();await selectTask(value.taskId);}catch(err){$('create-error').textContent=err.message;}finally{submit.disabled=false;}});});
  $('workflow').addEventListener('click',openWorkflow);$('add-step').addEventListener('click',()=>{if(workflowDraft.length>=40)return;workflowDraft.push({stepId:crypto.randomUUID(),title:'',participantId:task.coordinatorParticipantId,dependsOn:[],attempts:[]});renderWorkflow();});
  $('workflow-form').addEventListener('submit',event=>{event.preventDefault();guard(async()=>{try{await mutate('set_workflow',{steps:workflowDraft.map(({stepId,title,participantId,dependsOn})=>({stepId,title,participantId,dependsOn})),expected_revision:workflowRevision});$('workflow-dialog').close();notice('流程已保存');}catch(err){$('workflow-error').textContent=err.message;}});});
  $('composer').addEventListener('submit',event=>{event.preventDefault();guard(()=>send(false));});$('send-run').addEventListener('click',()=>guard(()=>send(true)));$('draft').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)&&!event.isComposing){event.preventDefault();guard(()=>send(false));}});
  $('mention').addEventListener('click',()=>{$('recipient').focus();$('recipient').showPicker?.();});
  $('start').addEventListener('click',()=>guard(()=>run()));$('cancel').addEventListener('click',()=>guard(async()=>{const id=task.taskId,generation=loadGeneration;const value=await invoke('cancel_task',{task_id:id});if(generation===loadGeneration){task=value;render();}await refreshList();}));
  $('refresh').addEventListener('click',()=>guard(async()=>{await refreshList();if(task){const id=task.taskId,generation=loadGeneration;const value=await invoke('refresh_task',{task_id:id});if(generation===loadGeneration){task=value;render();await loadActivity();}}}));
  $('history').addEventListener('click',()=>guard(async()=>{const rows=await invoke('list_external_runs',{limit:50});$('history-list').replaceChildren(...rows.map(row=>{const el=node('div',undefined,'card');el.append(node('h3',row.executionId),node('p',`${labels[row.status] || row.status} · ${row.providerConfigId}`,'muted'));return el;}));if(!rows.length)$('history-list').append(node('p','暂无历史委托。'));$('history-dialog').showModal();}));
  setInterval(()=>{if(!task || busy || polling || document.querySelector('dialog[open]') || (tab==='agents' && $('panel').contains(document.activeElement)))return;polling=true;guard(async()=>{const id=task.taskId,generation=loadGeneration;const value=await invoke('refresh_task',{task_id:id});if(generation!==loadGeneration)return;if(value.revision!==task.revision){task=value;render();await refreshList();}await loadActivity();}).finally(()=>polling=false);},1800);
  render();guard(async()=>{notice('正在加载…');await refreshList();[providers,natives]=await Promise.all([invoke('list_providers'),invoke('native_participants')]);if(tasks.length)await selectTask(tasks[0].taskId);notice('');});
})();
