// Appended only to the isolated QA prelude, never to a production bundle.
export const scrollFixture = String.raw`(()=>{
  if(!window.__qa)throw Error('Requires the isolated fixture');
  const previous=window.fetch;
  const response=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
  const message=(id,conversation=1)=>({id,conversation_id:conversation,direction:'inbound',content:'合成滚动验收消息 '+id+'：用于验证最新消息位置与历史阅读位置。',received_at:new Date(Date.UTC(2026,8,10,8,0,id)).toISOString(),source_item_external_id:null});
  window.fetch=async(url,options)=>{
    const u=String(url),path=new URL(u,location.origin);
    if(/^\/api\/conversations\/[12]$/.test(path.pathname)){
      const r=await previous(url,options),data=await r.json();
      if(data.id===2)await new Promise(resolve=>setTimeout(resolve,250));
      return response({...data,messages:Array.from({length:60},(_,i)=>message(i+101,data.id)),has_older_messages:true});
    }
    if(/^\/api\/conversations\/[12]\/messages$/.test(path.pathname)){
      window.__qa.calls.push({url:u,method:'GET'});
      return response({messages:Array.from({length:20},(_,i)=>message(i+81)),has_more:false});
    }
    if(path.pathname.endsWith('/conversation-group-candidates')){
      window.__qa.calls.push({url:u,method:'GET'});
      return response({conversations:[],groups:[{id:'qa-scroll-group',title:'合成会话组',revision:1,active:true,conversation_ids:[1,2],customer_id:'qa-customer'}]});
    }
    if(path.pathname==='/api/conversation-groups/qa-scroll-group/timeline'){
      window.__qa.calls.push({url:u,method:'GET'});
      const offset=Number(path.searchParams.get('offset')),limit=Number(path.searchParams.get('limit'));
      return response({messages:Array.from({length:Math.min(limit,250-offset)},(_,i)=>message(offset+i+1)),total_count:250,has_more:offset+limit<250});
    }
    return previous(url,options);
  };
})();`;
