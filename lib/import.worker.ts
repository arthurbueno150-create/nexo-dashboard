import * as XLSX from 'xlsx';
import {parseCSV,type Book,type Cell,type Matrix} from './engine';
self.onmessage=async(event:MessageEvent<{buffer:ArrayBuffer;name:string}>)=>{
 try{
 const {buffer,name}=event.data;const extension=name.split('.').pop()?.toLowerCase();
 let sheets:Book['sheets'];
 if(extension==='csv'||extension==='tsv'){
 let text=new TextDecoder('utf-8').decode(buffer);if(text.includes('\uFFFD'))text=new TextDecoder('windows-1252').decode(buffer);
 sheets=[{name:'Dados',data:parseCSV(text,extension==='tsv'?'\t':undefined)}];
 }else{
 const book=XLSX.read(buffer,{type:'array',cellDates:true,sheetRows:50002,cellFormula:false,cellHTML:false});
 sheets=book.SheetNames.map(name=>{
 const sheet=book.Sheets[name];const range=XLSX.utils.decode_range(sheet['!fullref']||sheet['!ref']||'A1');
 if(range.e.r>50000||range.e.c>=200||(range.e.r+1)*(range.e.c+1)>300000)throw Error('Esta aba ultrapassa o limite de 50.000 linhas, 200 colunas ou 300.000 células.');
 const raw=XLSX.utils.sheet_to_json(sheet,{header:1,defval:null,raw:true,blankrows:true}) as unknown[][];
 const data:Matrix=raw.map(row=>row.map(v=>v instanceof Date?v.toISOString().slice(0,10):typeof v==='number'||typeof v==='boolean'||typeof v==='string'?v:null as Cell));
 return {name,data};
 });
 }
 const cells=sheets.reduce((n,s)=>n+s.data.reduce((a,r)=>a+r.length,0),0);
 if(cells>500000)throw Error('A pasta de trabalho ultrapassa o limite de 500.000 células. Importe as abas separadamente.');
 for(const sheet of sheets)if(sheet.data.length>50001||sheet.data.some(r=>r.length>200)||sheet.data.reduce((n,r)=>n+r.length,0)>300000)throw Error('Limite por aba: 50.000 registros, 200 colunas e 300.000 células.');
 sheets=sheets.filter(s=>s.data.some(r=>r.some(v=>v!==null&&v!=='')));
 if(!sheets.length)throw Error('O arquivo não contém células preenchidas.');
 self.postMessage({book:{name,sheets}});
 }catch(error){self.postMessage({error:error instanceof Error?error.message:'Não foi possível ler o arquivo.'})}
};

