/* Block-entry automation editor. Drafts survive controller refreshes. */
(function (global) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy = value => JSON.parse(JSON.stringify(value));
  const option = (value, label, selected) => `<option value="${esc(value)}"${String(value) === String(selected) ? ' selected' : ''}>${esc(label)}</option>`;
  function create({ root, request, onChange }) {
    let data = {}, busy = false, signature = '', draft = fresh();
    function fresh() { return {name:'',block_id:'',enabled:true,train_scope:'any',train_ids:[],direction:'both',detector:null,actions:[{type:'function',target:'locomotive',function_number:0,mode:'pulse',duration_s:1}]}; }
    root.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">BLOCK ENTRY ACTIONS</p><h2 id="track-trigger-heading">Track triggers</h2></div><button type="button" class="button button-soft" data-trigger-new>New trigger</button></div>
      <div class="track-trigger-content"><p class="muted">Run functions or a saved routine when a train enters a block. Each detector re-arms when the block clears.</p>
      <div data-trigger-list></div><details data-trigger-editor open><summary>New trigger</summary><form data-trigger-form></form></details>
      <details data-trigger-position hidden><summary>Confirm a train’s position</summary><p class="muted">Occupancy detects a train, but cannot read its identity. Confirm its current block and planned route before driving. An unresolved new entry can also be confirmed here.</p><div data-position-fields></div></details>
      <p data-trigger-status role="status" aria-live="polite"></p></div>`;
    const q = selector => root.querySelector(selector);
    const form = q('[data-trigger-form]');
    const message = (value, error=false) => { const node=q('[data-trigger-status]'); node.textContent=value; node.classList.toggle('danger-text', error); };
    const labelTrain = train => `${train.name || train.id} · #${train.number || train.address || train.id}`;
    const trains = () => data.trains || [];
    const blocks = () => data.blocks || [];
    const inventory = () => (data.inventory || []).filter(item => item.decoder_address != null && (item.decoder_functions || []).length);
    function editor() {
      const d=draft;
      q('[data-trigger-editor] summary').textContent=d.id ? `Edit ${d.name}` : 'New trigger';
      form.innerHTML = `<div class="track-trigger-fields">
        <label>Name<input name="name" maxlength="80" placeholder="Platform lights" value="${esc(d.name)}" required></label>
        <label>Trigger block<select name="block_id" required>${option('','Choose a block…',d.block_id)}${blocks().map(b=>option(b.id,`${b.name || b.id} · ${b.id}`,d.block_id)).join('')}</select></label>
        <label>Applies to<select name="train_scope">${option('any','Any passing train',d.train_scope)}${option('selected','Selected trains',d.train_scope)}</select></label>
        <label>Direction<select name="direction">${option('both','Both directions',d.direction)}${option('forward','Forward',d.direction)}${option('reverse','Reverse',d.direction)}</select></label>
        <label class="track-trigger-check"><input name="enabled" type="checkbox" ${d.enabled?'checked':''}> Enabled</label>
      </div><fieldset data-trigger-trains ${d.train_scope==='any'?'hidden':''}><legend>Selected trains</legend><div class="track-trigger-trains">${trains().map(t=>`<label class="track-trigger-check"><input type="checkbox" name="train_ids" value="${esc(t.id)}" ${d.train_ids.includes(t.id)?'checked':''}>${esc(labelTrain(t))}</label>`).join('') || '<p>No trains available.</p>'}</div></fieldset>
      <details class="track-trigger-detector" ${d.detector?'open':''}><summary>Occupancy detector mapping</summary><p class="muted">Use the module and input reported by your command station, or leave both empty to use an existing block mapping. Switch track power off to change mappings. Simulation uses train movement.</p><div class="track-trigger-fields"><label>Module<input type="number" min="0" max="65535" name="detector_module" placeholder="Module" value="${esc(d.detector?.module)}"></label><label>Input<input type="number" min="1" max="65535" name="detector_input" placeholder="Input" value="${esc(d.detector?.input)}"></label></div><p class="muted" data-existing-mapping></p></details>
      <h3>Actions</h3><p class="muted">Functions target the passing train’s locomotive or a car in its consist. Cars sharing a DCC address switch together. Saved routines run on the passing train.</p>
      <div class="track-trigger-actions">${d.actions.map((a,i)=>actionRow(a,i)).join('')}</div>
      <div class="track-trigger-buttons"><button type="button" class="button button-soft" data-trigger-add="function">+ Function</button><button type="button" class="button button-soft" data-trigger-add="routine">+ Saved routine</button><button class="button button-primary" type="submit">${d.id?'Save changes':'Save trigger'}</button><button type="button" class="text-button" data-trigger-cancel>Cancel</button></div>`;
      showMapping();
    }
    function actionRow(a,i) {
      const selectedStock=inventory().find(item=>item.id===a.item_id);
      const functions=a.target==='rolling_stock' && selectedStock ? selectedStock.decoder_functions.map(f=>option(f.function_number,`F${f.function_number} · ${f.label || f.name || 'Function'}`,a.function_number)) : Array.from({length:32},(_,n)=>option(n,`F${n}`,a.function_number));
      const controls=a.type==='routine'
        ? `<label>Saved routine<select data-field="program_id" required>${option('','Choose a routine…',a.program_id)}${(data.programs||[]).map(p=>option(p.id,p.name || p.id,a.program_id)).join('')}</select></label>`
        : `<label>Decoder<select data-field="target">${option('locomotive','Locomotive',a.target)}${option('rolling_stock','Rolling stock',a.target)}</select></label>
          ${a.target==='rolling_stock'?`<label>Car entry<select data-field="item_id" required>${option('','Choose rolling stock…',a.item_id)}${inventory().map(s=>option(s.id,`${s.name || s.id} · DCC #${s.decoder_address}`,a.item_id)).join('')}</select></label>`:''}
          <label>Function<select data-field="function_number">${functions.join('')}</select></label>
          <label>Action<select data-field="mode">${option('on','Turn on',a.mode)}${option('off','Turn off',a.mode)}${option('pulse','Timed pulse',a.mode)}</select></label>
          ${a.mode==='pulse'?`<label>Real seconds<input type="number" min="0.1" max="60" step="0.1" data-field="duration_s" value="${esc(a.duration_s??1)}" required></label>`:''}`;
      return `<div class="track-trigger-action" data-action-index="${i}"><span class="track-trigger-action-number">${i+1}</span>${controls}<button type="button" class="text-button danger-text" data-trigger-remove="${i}" aria-label="Remove action ${i+1}">Remove</button></div>`;
    }
    function read() {
      const fields=new FormData(form);
      Object.assign(draft,{name:fields.get('name'),block_id:fields.get('block_id'),train_scope:fields.get('train_scope'),direction:fields.get('direction'),enabled:fields.has('enabled'),train_ids:fields.getAll('train_ids')});
      const mod=fields.get('detector_module'), input=fields.get('detector_input');
      draft.detector=mod!=='' || input!=='' ? {module:Number(mod),input:Number(input)} : null;
      form.querySelectorAll('[data-action-index]').forEach(row=>row.querySelectorAll('[data-field]').forEach(el=> {
        const key=el.dataset.field;
        draft.actions[Number(row.dataset.actionIndex)][key]=['function_number','duration_s'].includes(key)?Number(el.value):el.value;
      }));
      return copy(draft);
    }
    function showMapping() {
      const block=form.elements.block_id?.value;
      const mapping=(data.triggers?.feedback_map||[]).filter(m=>m.block_id===block).map(m=>`module ${m.module}, input ${m.input}`).join('; ');
      const node=q('[data-existing-mapping]');
      if(node) node.textContent=mapping ? `Current mapping: ${mapping}` : 'No detector mapped to this block yet.';
    }
    async function command(payload) {
      if(busy) return null;
      busy=true;
      root.setAttribute('aria-busy','true');
      try {
        const response=await request('/api/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        onChange(response);
        return response;
      } catch(error) { message(error.message,true); return null; }
      finally { busy=false; root.removeAttribute('aria-busy'); }
    }
    form.addEventListener('change',event=> {
      read();
      q('[data-trigger-trains]').hidden=draft.train_scope==='any';
      showMapping();
      if(event.target.dataset.field==='item_id') {
        const index=Number(event.target.closest('[data-action-index]').dataset.actionIndex);
        const item=inventory().find(s=>s.id===event.target.value);
        if(item?.decoder_functions?.length) draft.actions[index].function_number=item.decoder_functions[0].function_number;
      }
      if(['target','mode','item_id'].includes(event.target.dataset.field)) editor();
    });
    form.addEventListener('submit',async event=> {
      event.preventDefault();
      const value=read();
      if(value.detector && (!form.elements.detector_module.value || !form.elements.detector_input.value)) { message('Enter both the detector module and input.',true); return; }
      if(await command({type:'save_track_trigger',trigger:value})) { draft=fresh(); editor(); q('[data-trigger-editor]').open=false; message('Track trigger saved.'); }
    });
    root.addEventListener('click',async event=> {
      const button=event.target.closest('button');
      if(!button || busy) return;
      if(button.hasAttribute('data-trigger-new')) { draft=fresh(); editor(); q('[data-trigger-editor]').open=true; form.elements.name.focus(); }
      else if(button.hasAttribute('data-trigger-cancel')) { draft=fresh(); editor(); q('[data-trigger-editor]').open=false; message(''); }
      else if(button.hasAttribute('data-trigger-add')) { read(); if(draft.actions.length>=16) {message('A trigger supports up to 16 actions.',true);return;} draft.actions.push(button.dataset.triggerAdd==='routine'?{type:'routine',program_id:''}:{type:'function',target:'locomotive',function_number:0,mode:'pulse',duration_s:1}); editor(); }
      else if(button.hasAttribute('data-trigger-remove')) { read(); draft.actions.splice(Number(button.dataset.triggerRemove),1); editor(); }
      else if(button.hasAttribute('data-trigger-edit')) { draft=copy((data.triggers?.definitions||[]).find(d=>d.id===button.dataset.triggerEdit)); editor(); q('[data-trigger-editor]').open=true; form.elements.name.focus(); }
      else if(button.hasAttribute('data-trigger-delete')) { if(await command({type:'delete_track_trigger',trigger_id:button.dataset.triggerDelete})) { if(draft.id===button.dataset.triggerDelete) {draft=fresh();editor();} message('Track trigger removed.'); } }
      else if(button.hasAttribute('data-trigger-toggle')) { const item=(data.triggers?.definitions||[]).find(d=>d.id===button.dataset.triggerToggle); await command({type:'save_track_trigger',trigger:{...item,enabled:!item.enabled}}); }
    });
    q('[data-trigger-position]').addEventListener('submit',async event=> {
      event.preventDefault();
      const fields=new FormData(event.target), block=fields.get('block_id');
      const route=String(fields.get('route')||'').split(/[,\s]+/).filter(Boolean).map(id=>id.toUpperCase());
      if(await command({type:'report_train_position',train_id:fields.get('train_id'),block_id:block,route:route.length?route:[block]})) message('Train position confirmed.');
    });
    q('[data-trigger-position]').addEventListener('change',event=> {
      if(event.target.name!=='train_id') return;
      const train=trains().find(t=>t.id===event.target.value), fields=event.target.form.elements;
      if(blocks().some(b=>b.id===train?.position)) fields.block_id.value=train.position;
      fields.route.value=(train?.route || []).join(', ');
    });
    function positionEditor() {
      const previous=q('.track-trigger-position-form');
      const old=previous?new FormData(previous):null;
      const train=trains().find(t=>t.id===old?.get('train_id')) || trains()[0];
      q('[data-position-fields]').innerHTML=`<form class="track-trigger-position-form"><div class="track-trigger-fields"><label>Train<select name="train_id" required>${trains().map(t=>option(t.id,labelTrain(t),'')).join('')}</select></label><label>Current block<select name="block_id" required>${blocks().map(b=>option(b.id,b.name || b.id,'')).join('')}</select></label><label class="track-trigger-route">Planned route<input name="route" placeholder="B01, B02, B03"><small>Connected block IDs in travel order. Leave empty for the current block only.</small></label></div><button type="submit" class="button button-soft">Confirm train position</button></form>`;
      const fields=q('.track-trigger-position-form').elements;
      if(train) fields.train_id.value=train.id;
      const block=old?.get('block_id') || train?.position;
      if(blocks().some(b=>b.id===block)) fields.block_id.value=block;
      fields.route.value=old?.get('route') ?? (train?.route || []).join(', ');
    }
    function actionLabel(a) {
      if(a.type==='routine') return `Routine: ${(data.programs||[]).find(p=>p.id===a.program_id)?.name || a.program_id}`;
      const stock=inventory().find(s=>s.id===a.item_id);
      return `${a.target==='rolling_stock'?(stock?.name || a.item_id):'Locomotive'} · F${a.function_number} ${a.mode==='pulse'?`pulse ${a.duration_s??1}s`:a.mode}`;
    }
    function render(value) {
      data=value;
      const next=JSON.stringify([blocks().map(b=>[b.id,b.name]),trains().map(t=>[t.id,t.name]),(data.programs||[]).map(p=>[p.id,p.name]),inventory().map(s=>[s.id,s.name,s.decoder_address,s.decoder_functions])]);
      if(signature!==next && !form.contains(document.activeElement)) { if(signature) read(); editor(); signature=next; }
      q('[data-trigger-position]').hidden=!data.physical;
      const fields=q('[data-position-fields]');
      if(!fields.innerHTML || (fields.dataset.signature!==next && !fields.contains(document.activeElement))) { positionEditor(); fields.dataset.signature=next; }
      const definitions=data.triggers?.definitions || [], results=data.triggers?.results || [];
      q('[data-trigger-list]').innerHTML=definitions.length ? definitions.map(d=> {
        const result=results.find(r=>r.trigger_id===d.id);
        const missing=!blocks().some(b=>b.id===d.block_id);
        const mapped=(data.triggers?.feedback_map || []).some(m=>m.block_id===d.block_id);
        const state=!d.enabled?'Disabled':missing?'Block not in this layout':data.physical&&!mapped?'Needs detector mapping':result?.status || 'Ready';
        return `<article class="track-trigger-row"><div><strong>${esc(d.name)}</strong><span class="track-trigger-state">${esc(state)}</span><p class="muted">${esc(d.block_id)} · ${d.train_scope==='any'?'Any train':`${d.train_ids.length} selected trains`} · ${esc(d.direction==='both'?'Both directions':d.direction)}</p><p>${esc(d.actions.map(actionLabel).join(' · '))}</p>${result?`<p class="muted">${esc(new Date(result.time*1000).toLocaleTimeString())}${result.train_id?` · Train ${esc(result.train_id)}`:''}${result.detail?` · ${esc(result.detail)}`:''}</p>`:''}</div><div class="track-trigger-buttons"><button type="button" class="text-button" data-trigger-edit="${esc(d.id)}">Edit</button><button type="button" class="text-button" data-trigger-toggle="${esc(d.id)}">${d.enabled?'Disable':'Enable'}</button><button type="button" class="text-button danger-text" data-trigger-delete="${esc(d.id)}">Delete</button></div></article>`;
      }).join('') : '<p class="empty-state">No track triggers yet. Add one to automate a passing train’s functions.</p>';
      showMapping();
    }
    editor();
    return {render};
  }
  global.TrackTriggers={create};
})(window);
