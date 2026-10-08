"use strict";
const $ = id => document.getElementById(id);
let state = null, historyKey = "", deleting = null;
const size = bytes => bytes >= 1073741824 ? (bytes/1073741824).toFixed(2)+" GiB" : (bytes/1048576).toFixed(1)+" MiB";
const timestamp = seconds => {const m=Math.floor(seconds/60);return `${m}:${(seconds%60).toFixed(1).padStart(4,"0")}`;};
const node = (tag,text,cls) => {const el=document.createElement(tag); if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
async function action(name, payload={}) {
  $("message").textContent="";
  try {const response=await fetch(`/api/${name}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error);await refresh();return result;}
  catch(error){$("message").textContent=error.message;return null;}
}
function renderHistory(items,current,job){
  const key=JSON.stringify([items,current?.video_id,job?.status==="working"?job.video_id:null]);if(key===historyKey)return;historyKey=key;
  $("history").replaceChildren();
  if(!items.length){$("history").append(node("p","動画を準備すると、ここから再選択できます。","empty"));return;}
  for(const video of items){
    const card=node("article",undefined,"card");
    if(video.thumbnail_url){const img=node("img");img.className="thumbnail";img.src=video.thumbnail_url;img.alt="";img.loading="lazy";img.addEventListener("error",()=>{img.replaceWith(node("div","サムネイルなし","thumbnail placeholder"));});card.append(img);}
    else card.append(node("div","サムネイルなし","thumbnail placeholder"));
    const body=node("div",undefined,"card-body");body.append(node("h3",video.title),node("p",video.channel));
    if(video.uploader && video.uploader!==video.channel)body.append(node("p",video.uploader));
    body.append(node("p",`${timestamp(video.duration)} · ${size(video.bytes)}`));
    const link=node("a","元の動画を開く");link.href=video.url;link.target="_blank";link.rel="noopener noreferrer";body.append(link);
    const list=node("div",undefined,"cache-list");
    for(const conversion of video.conversions){const b=node("button",`${conversion.fps}fps · ${timestamp(conversion.start)}–${timestamp(conversion.end)}`,"secondary cache-button");b.addEventListener("click",()=>action("play",{key:conversion.key}));b.disabled=job?.status==="working";list.append(b);}
    if(!video.conversions.length)list.append(node("p","完成した変換データはまだありません"));body.append(list);
    const sources=video.sources.map(s=>s.full?"全編":`部分 ${timestamp(s.start)}–${timestamp(s.end)}`).join(" / ");
    if(sources)body.append(node("p",`元動画: ${sources}`));
    const prepare=node("button","この動画を選ぶ","secondary");prepare.addEventListener("click",()=>{$("url").value=video.url;$("url").focus();window.scrollTo({top:0,behavior:"smooth"});});body.append(prepare);
    const del=node("button","この動画を削除","delete-button");del.disabled=current?.video_id===video.id || (job?.status==="working"&&job.video_id===video.id);del.title=del.disabled?"再生停止・処理取消し後に削除できます":"";
    del.addEventListener("click",()=>{deleting=video;$("delete-title").textContent=video.title;$("delete-size").textContent=`使用量: ${size(video.bytes)}`;$("delete-dialog").showModal();});body.append(node("br"),del);card.append(body);$("history").append(card);
  }
}
async function refresh(){
  try{const r=await fetch("/api/state");if(!r.ok)throw new Error("接続失敗");state=await r.json();const {playback,job,usage,history}=state;const current=playback.current;
    $("connection").textContent=playback.connected?"Pico 接続中":"Pico 待機中";
    $("now-title").textContent=current?.title || "停止中";
    $("now-detail").textContent=current?`${current.fps} fps · ${timestamp(current.start)}–${timestamp(current.end)} · ${current.loop+1}周目（配信時刻）`:"動画を選んでください";
    if(current && document.activeElement!==$("now-fps"))$("now-fps").value=String(current.fps);
    $("stop").disabled=!current;$("change-fps").disabled=!current || job?.status==="working";
    const working=job?.status==="working";$("prepare").disabled=working;$("cancel").hidden=!working;$("job").hidden=!job;
    if(job){$("job-message").textContent=job.message;$("progress").value=job.progress||0; if(working && job.stage!=="convert")$("progress").removeAttribute("value");}
    $("usage").replaceChildren(node("div",`使用 ${size(usage.total)} / 空き ${size(usage.free)}`),node("div",`元動画 ${size(usage.source)} · 変換 ${size(usage.converted)}`));
    renderHistory(history,current,job);
  }catch(error){$("connection").textContent="サーバーとの接続を確認してください";}
}
$("prepare-form").addEventListener("submit",event=>{event.preventDefault();action("prepare",{url:$("url").value,fps:Number($("fps").value),start:$("start").value,end:$("end").value});});
$("change-fps").addEventListener("click",()=>action("fps",{fps:Number($("now-fps").value)}));
$("stop").addEventListener("click",()=>action("stop"));$("cancel").addEventListener("click",()=>action("cancel"));
$("delete-cancel").addEventListener("click",()=>$("delete-dialog").close());
$("delete-confirm").addEventListener("click",async()=>{if(deleting){const result=await action("delete",{video_id:deleting.id,confirmation:deleting.id});if(result)$("delete-dialog").close();}});
refresh();setInterval(refresh,2000);
