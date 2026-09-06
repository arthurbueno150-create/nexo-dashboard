export type Cell = string | number | boolean | null;
export type Matrix = Cell[][];
export type Book = {name:string; sheets:{name:string; data:Matrix}[]; demo?:string};
export type Rules = {trim:boolean; deduplicate:boolean};
export type Column = {index:number; name:string; kind:'number'|'date'|'text'; missing:number};
export type Dataset = {columns:Column[]; rows:Cell[][]; emptyRows:number; duplicates:number; removed:number; missing:number; header:number};
export type Mapping = {metric:number; group:number; date:number; type:number; mode:'general'|'finance'; currency:boolean};
export type Filters = {search:string; category:string; start:string; end:string};
export const normalize=(s:unknown)=>String(s??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
export const empty=(v:unknown)=>v===null||v===undefined||typeof v==='string'&&!v.trim();
export function numberValue(v:unknown):number|null {
 if(typeof v==='number')return Number.isFinite(v)?v:null;
 if(typeof v!=='string'||!v.trim())return null;
 let s=v.trim().replace(/^(R\$|US\$|\$|€|£)\s*/,'').replace(/\s/g,'');
 const paren=/^\(.*\)$/.test(s); if(paren)s='-'+s.slice(1,-1);
 if(!/^[+-]?\d[\d.,]*%?$/.test(s))return null;
 const percent=s.endsWith('%');if(percent)s=s.slice(0,-1);
 if(s.includes(',')&&s.includes('.'))s=s.lastIndexOf(',')>s.lastIndexOf('.')?s.replace(/\./g,'').replace(',','.'):s.replace(/,/g,'');
 else if(s.includes(','))s=/^[+-]?\d{1,3}(,\d{3}){2,}$/.test(s)?s.replace(/,/g,''):s.replace(',','.');
 else if(/^[+-]?\d{1,3}(\.\d{3})+$/.test(s))s=s.replace(/\./g,'');
 const n=Number(s);return Number.isFinite(n)?n/(percent?100:1):null;
}
export function dateValue(v:unknown):string|null {
 if(typeof v!=='string')return null;
 const s=v.trim();let y:number,m:number,d:number;
 let match=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/);
 if(match){y=+match[1];m=+match[2];d=+match[3]}else{match=s.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{4})$/);if(!match)return null;d=+match[1];m=+match[2];y=+match[3]}
 const date=new Date(Date.UTC(y,m-1,d));
 return date.getUTCFullYear()===y&&date.getUTCMonth()===m-1&&date.getUTCDate()===d?date.toISOString().slice(0,10):null;
}
export function detectHeader(data:Matrix):number {
 let best=0,score=-1;
 data.slice(0,30).forEach((row,i)=>{
 const filled=row.filter(v=>!empty(v));const strings=filled.filter(v=>typeof v==='string'&&numberValue(v)===null&&dateValue(v)===null).length;
 const next=data.slice(i+1,i+5);const following=next.length?next.reduce((s,r)=>s+r.filter(v=>!empty(v)).length,0)/next.length:0;
 const value=filled.length+strings*.8+Math.min(following,filled.length)*.3-i*.12;
 if(value>score){score=value;best=i}
 });return best;
}
export function prepare(data:Matrix,header:number,rules:Rules):Dataset {
 const width=Math.max(0,...data.slice(header).map(r=>r.length));
 const used=new Set<string>();const names=Array.from({length:width},(_,i)=>{
 const base=String(data[header]?.[i]??'').trim()||'Coluna '+(i+1);let name=base,j=2;
 while(used.has(name)){name=base+' ('+j+++')'}used.add(name);return name;
 });
 let emptyRows=0,duplicates=0,removed=0;const seen=new Set<string>();
 const rows:Cell[][]=[];
 for(const source of data.slice(header+1)){
 const row=Array.from({length:width},(_,i)=>{const v=source[i]??null;return rules.trim&&typeof v==='string'?v.trim():v});
 if(row.every(empty)){emptyRows++;continue}
 const key=JSON.stringify(row);if(seen.has(key)){duplicates++;if(rules.deduplicate){removed++;continue}}seen.add(key);rows.push(row);
 }
 const columns:Column[]=names.map((name,index)=>{
 const values=rows.map(r=>r[index]).filter(v=>!empty(v));const sample=values.slice(0,1000);
 const idLike=/\b(id|codigo|cep|cpf|cnpj|telefone|sku|matricula)\b/.test(normalize(name))||sample.some(v=>typeof v==='string'&&/^0\d+$/.test(v));
 const dates=sample.filter(v=>dateValue(v)!==null).length;
 const nums=sample.filter(v=>numberValue(v)!==null).length;
 return {index,name,kind:sample.length&&dates/sample.length>=.8?'date':!idLike&&sample.length&&nums/sample.length>=.8?'number':'text',missing:rows.length-values.length};
 });
 return {columns,rows,emptyRows,duplicates,removed,missing:columns.reduce((s,c)=>s+c.missing,0),header};
}
export function inferMapping(data:Dataset):Mapping {
 const cols=data.columns;const find=(rx:RegExp,kind?:Column['kind'])=>cols.find(c=>(!kind||c.kind===kind)&&rx.test(normalize(c.name)))?.index??-1;
 const priority=find(/^(valor|receita|faturamento|total|saldo|valor em estoque)$/,'number');
 const metric=priority>=0?priority:find(/valor|receita|faturamento|total|saldo|preco|quantidade/,'number');
 const type=find(/^(tipo|natureza|movimento|type)$/);
 const group=find(/categoria|departamento|produto|canal|equipe|setor/);
 const chosen=metric>=0?metric:cols.find(c=>c.kind==='number')?.index??-1;
 const financial=type>=0&&data.rows.some(r=>direction(r[type])!==0);
 return {metric:chosen,group:group>=0?group:cols.find(c=>c.kind==='text'&&c.index!==type)?.index??-1,date:cols.find(c=>c.kind==='date')?.index??-1,type,mode:financial?'finance':'general',currency:financial||/valor|receita|faturamento|preco|saldo|custo/.test(normalize(cols[chosen]?.name))};
}
export function direction(v:unknown):number {
 const s=normalize(v);
 if(/^(receita|receitas|entrada|entradas|credito|income|revenue|credit)$/.test(s))return 1;
 if(/^(despesa|despesas|saida|saidas|debito|expense|expenses|debit)$/.test(s))return -1;
 return 0;
}
export function filterRows(data:Dataset,map:Mapping,filters:Filters):Cell[][] {
 const term=normalize(filters.search);
 return data.rows.filter(r=>{
 if(term&&!r.some(v=>normalize(v).includes(term)))return false;
 if(filters.category!=='all'&&String(r[map.group]??'Sem categoria')!==filters.category)return false;
 if(map.date>=0&&(filters.start||filters.end)){
 const d=dateValue(r[map.date]);if(!d||filters.start&&d<filters.start||filters.end&&d>filters.end)return false;
 }return true;
 });
}
export function analyze(rows:Cell[][],map:Mapping){
 let total=0,income=0,expense=0,valid=0,invalid=0,unclassified=0,undated=0;
 const groups=new Map<string,{name:string;value:number;count:number}>();
 const timeline=new Map<string,{name:string;value:number;income:number;expense:number;count:number}>();
 for(const r of rows){
 const n=map.metric>=0?numberValue(r[map.metric]):null;
 if(n===null&&map.metric>=0)invalid++;if(n!==null){valid++;total+=n}
 const dir=map.type>=0?direction(r[map.type]):n===null?0:n>=0?1:-1;
 const inc=map.mode==='finance'&&dir===1&&n!==null?Math.abs(n):0;
 const exp=map.mode==='finance'&&dir===-1&&n!==null?Math.abs(n):0;
 if(map.mode==='finance'&&n!==null&&!dir)unclassified++;
 income+=inc;expense+=exp;
 const group=map.group>=0?String(r[map.group]??'Sem categoria'):'Todos';
 const item=groups.get(group)||{name:group,value:0,count:0};item.count++;
 item.value+=map.mode==='finance'?exp:n??(map.metric<0?1:0);groups.set(group,item);
 if(map.date>=0){const date=dateValue(r[map.date]);if(date){const key=date.slice(0,7);const point=timeline.get(key)||{name:key,value:0,income:0,expense:0,count:0};point.value+=n??(map.metric<0?1:0);point.income+=inc;point.expense+=exp;point.count++;timeline.set(key,point)}else undated++}
 }
 return {total,income,expense,balance:income-expense,valid,invalid,unclassified,undated,average:valid?total/valid:0,groups:[...groups.values()].sort((a,b)=>Math.abs(b.value)-Math.abs(a.value)),timeline:[...timeline.values()].sort((a,b)=>a.name.localeCompare(b.name)),count:rows.length};
}
export function parseCSV(text:string,separator?:string):Matrix {
 text=text.replace(/^\uFEFF/,'');let sep=separator;
 if(!sep){const first=text.split(/\r?\n/).slice(0,5).join('\n');sep=[';',',','\t'].map(d=>({d,n:countOutside(first,d)})).sort((a,b)=>b.n-a.n)[0].d}
 const rows:Matrix=[];let row:Cell[]=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){
 const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++}else if(quoted||!cell){quoted=!quoted}else cell+=c}
 else if(!quoted&&c===sep){row.push(cell);cell=''}
 else if(!quoted&&(c==='\r'||c==='\n')){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';if(rows.length>50001)throw Error('Limite de 50.000 registros por aba.')}
 else cell+=c;
 }
 if(quoted)throw Error('O CSV contém aspas sem fechamento. Revise o arquivo.');
 if(cell||row.length){row.push(cell);rows.push(row)}return rows;
}
function countOutside(text:string,sep:string){let q=false,n=0;for(let i=0;i<text.length;i++){if(text[i]==='"'){if(q&&text[i+1]==='"')i++;else q=!q}else if(!q&&text[i]===sep)n++}return n}
export function toCSV(columns:Column[],rows:Cell[][]):string{
 const quote=(v:unknown)=>{let s=String(v??'');if(typeof v==='string'&&/^[\s]*[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'};
 return '\uFEFF'+[columns.map(c=>quote(c.name)).join(';'),...rows.map(r=>r.map(quote).join(';'))].join('\r\n');
}
export function demoBook(kind='finance'):Book {
 const rows:Matrix=[];
 if(kind==='finance'){
 rows.push(['Data','Descrição','Categoria','Tipo','Valor','Status']);
 const categories=['Operacional','Equipe','Marketing','Tecnologia'];const totals=[12800,17200,14500,23400,20800,28400,26300,32800];
 totals.forEach((total,m)=>{for(let i=0;i<16;i++){const expense=i>=8;rows.push(['2026-'+String(m+1).padStart(2,'0')+'-'+String(i+3).padStart(2,'0'),expense?['Aluguel e serviços','Folha de pagamento','Campanhas digitais','Software e ferramentas'][i%4]:'Recebimento de cliente '+(i+1),expense?categories[i%4]:'Vendas',expense?'Despesa':'Receita',expense?Math.round(total*(.48+m%3*.05)/8):total/8,i%7===0?'Pendente':'Concluído'])}});
 }else if(kind==='sales'){rows.push(['Data','Produto','Canal','Quantidade','Valor','Status']);for(let m=0;m<8;m++)for(let i=0;i<10;i++)rows.push(['2026-'+String(m+1).padStart(2,'0')+'-'+String(i+4).padStart(2,'0'),['Plano Pro','Plano Team','Consultoria'][i%3],['Site','Indicação','Parceiro'][i%3],i%4+1,(i%4+1)*[149,399,1200][i%3]+m*20,'Concluído'])}
 else {rows.push(['SKU','Produto','Categoria','Quantidade','Estoque mínimo','Custo unitário']);for(let i=0;i<30;i++)rows.push(['00'+(100+i),['Teclado','Monitor','Mouse','Headset','Notebook'][i%5]+' '+(i+1),['Periféricos','Telas','Periféricos','Áudio','Computadores'][i%5],(i*13)%70,10,[180,1100,89,240,4500][i%5]])}
 return {name:kind==='finance'?'Financeiro 2026':kind==='sales'?'Vendas 2026':'Controle de estoque',demo:kind,sheets:[{name:'Dados',data:rows}]};
}


