const ui={message:document.querySelector('#message'),sample:document.querySelector('#sample-name'),file:document.querySelector('#scan-file')};
async function requestRun(url,body,isFile=false){ui.message.textContent='正在核算…';try{const options={method:'POST',body:isFile?body:JSON.stringify(body)};if(!isFile)options.headers={'Content-Type':'application/json'};const res=await fetch(url,options);const result=await res.json();if(!res.ok)throw new Error(result.message);window.location.reload();}catch(e){ui.message.textContent=e.message;}}
document.querySelector('#retry')?.addEventListener('click',()=>requestRun('/api/runs',{sample:ui.sample.value}));
document.querySelector('#read-file')?.addEventListener('click',()=>{if(!ui.file.files.length){ui.message.textContent='请选择扫描文件。';return;}const data=new FormData();data.append('file',ui.file.files[0]);requestRun('/api/upload',data,true);});
document.querySelector('#review-run')?.addEventListener('click',()=>requestRun('/api/runs/'+window.parcelRun.id+'/review',{version:window.parcelRun.version,decision:'已复核'}));
document.querySelector('#search-scans')?.addEventListener('input',event=>{document.querySelectorAll('#scan-rows tr').forEach(row=>{row.hidden=!row.textContent.includes(event.target.value);});});
const supplementInput=document.querySelector('#supplement-file');
document.querySelector('#submit-supplement')?.addEventListener('click',async()=>{
  const note=document.querySelector('#correction-message');
  if(!supplementInput.files.length){note.textContent='请选择补传扫描CSV。';return;}
  note.textContent='正在合并重算，原批保持冻结…';
  try{
    const text=await supplementInput.files[0].text();
    const res=await fetch('/api/runs/'+window.parcelRun.id+'/corrections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv:text})});
    const result=await res.json();
    if(!res.ok)throw new Error(result.message);
    window.location.href='/archives?run='+result.run.run_id;
  }catch(e){note.textContent=e.message;}
});
async function reviewCorrection(decision){
  try{
    const res=await fetch('/api/corrections/'+window.parcelRun.id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:window.parcelRun.version,decision})});
    const result=await res.json();
    if(!res.ok)throw new Error(result.message);
    window.location.reload();
  }catch(e){window.alert(e.message);}
}
document.querySelector('#confirm-correction')?.addEventListener('click',()=>reviewCorrection('已复核'));
document.querySelector('#reject-correction')?.addEventListener('click',()=>reviewCorrection('退回复核'));
