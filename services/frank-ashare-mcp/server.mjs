import { createServer } from 'node:http';
const ORIGIN='https://assets.stock-frankhong.com/v1/valuation';
const name='get_ashare_valuation';
function send(res,status,data){res.writeHead(status,{'content-type':'application/json','cache-control':'no-store','x-content-type-options':'nosniff'});res.end(JSON.stringify(data))}
function ok(id,result){return {jsonrpc:'2.0',id,result}}
const tool={name,description:'Read-only A-share closing valuation; includes date, freshness and coverage.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,destructiveHint:false}};
createServer(async(req,res)=>{
 try{
  if(req.url==='/health'&&req.method==='GET')return send(res,200,{status:'ok',service:'frank-ashare-mcp'});
  if(req.url!=='/mcp')return send(res,404,{error:'not found'});
  if(req.method!=='POST')return send(res,405,{error:'POST required'});
  const origin=req.headers.origin;
  if(origin&&!['https://chatgpt.com','https://chat.openai.com'].includes(origin))return send(res,403,{error:'forbidden origin'});
  const auth=req.headers.authorization||'';const m=auth.startsWith('Bearer ')&&auth.slice(7).length&&!auth.slice(7).includes(' ')?[auth,auth.slice(7)]:null;
  if(!m)return send(res,401,{error:'Bearer API Key required'});
  if(!(req.headers['content-type']||'').toLowerCase().startsWith('application/json'))return send(res,415,{error:'JSON required'});
  let raw='';for await(const chunk of req){raw+=chunk.toString();if(raw.length>65536)return send(res,413,{error:'request too large'})}
  let rpc;try{rpc=JSON.parse(raw)}catch{return send(res,400,{error:'invalid JSON'})}
  if(!rpc||typeof rpc!=='object'||Array.isArray(rpc)||rpc.jsonrpc!=='2.0')return send(res,400,{error:'invalid JSON-RPC'});
  if(!Object.hasOwn(rpc,'id')){res.writeHead(202);return res.end()}
  const id=rpc.id;
  if(rpc.method==='initialize')return send(res,200,ok(id,{protocolVersion:'2025-06-18',capabilities:{tools:{listChanged:false}},serverInfo:{name:'frank-ashare-mcp',version:'0.2.0'}}));
  if(rpc.method==='ping')return send(res,200,ok(id,{}));
  if(rpc.method==='tools/list')return send(res,200,ok(id,{tools:[tool]}));
  if(rpc.method!=='tools/call')return send(res,200,{jsonrpc:'2.0',id,error:{code:-32601,message:'Method not found'}});
  if(rpc.params?.name!==name||Object.keys(rpc.params?.arguments||{}).length)return send(res,200,ok(id,{isError:true,content:[{type:'text',text:'Unknown tool or invalid arguments'}]}));
  let message,data;
  try{
   const response=await fetch(ORIGIN,{method:'GET',headers:{Authorization:'Bearer '+m[1],Accept:'application/json'},redirect:'manual',signal:AbortSignal.timeout(20000)});
   if(!response.ok){message='Upstream returned HTTP '+response.status;throw Error(message)}
   const buf=await response.arrayBuffer();if(buf.byteLength>2000000)throw Error('Response too large');
   data=JSON.parse(Buffer.from(buf).toString('utf8'));
   if(!data||!['valuation_date','freshness','usable_for_current_report','positions','totals','coverage'].every(k=>k in data))throw Error('Invalid valuation snapshot');
  }catch(e){return send(res,200,ok(id,{isError:true,content:[{type:'text',text:e.message==='Invalid valuation snapshot'?'Invalid valuation snapshot':e.message?.startsWith('Upstream returned HTTP')?e.message:'Upstream valuation unavailable'}]}))}
  return send(res,200,ok(id,{content:[{type:'text',text:JSON.stringify(data)}],structuredContent:data}));
 }catch{return send(res,500,{error:'Internal server error'})}
}).listen(Number(process.env.PORT||10000),'0.0.0.0');
