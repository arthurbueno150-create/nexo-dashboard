import test from 'node:test';
import assert from 'node:assert/strict';
import {analyze,dateValue,detectHeader,filterRows,inferMapping,numberValue,parseCSV,prepare,toCSV,demoBook} from '../lib/engine.ts';
const rules={trim:true,deduplicate:false};
test('lê valores brasileiros, americanos, negativos e percentuais sem converter IDs',()=>{
 for(const [raw,value] of [['R$ 1.234,56',1234.56],['1,234.56',1234.56],['(420,50)',-420.5],['1.234',1234],['10%',.1],[0,0],['abc',null],['',null],['2026-01-02',null]])assert.equal(numberValue(raw),value);
 const d=prepare([['SKU','Valor'],['00123',12],['00124',15]],0,rules);assert.equal(d.columns[0].kind,'text');assert.equal(d.rows[0][0],'00123');
});
test('valida datas brasileiras, anos bissextos e datas impossíveis',()=>{
 assert.equal(dateValue('29/02/2024'),'2024-02-29');assert.equal(dateValue('29/02/2025'),null);assert.equal(dateValue('31/04/2026'),null);assert.equal(dateValue('2026-12-03'),'2026-12-03');assert.equal(dateValue('12/31/2026'),null);
});
test('CSV com ponto e vírgula, BOM, linhas multilinha e aspas escapadas',()=>{
 const rows=parseCSV('\uFEFFNome;Valor\r\n"Cliente; A";"1.200,50"\r\n"Texto\nmultilinha";0\r\n"Disse ""oi""";22');
 assert.equal(rows.length,4);assert.equal(rows[1][0],'Cliente; A');assert.equal(rows[2][0],'Texto\nmultilinha');assert.equal(rows[3][0],'Disse "oi"');assert.throws(()=>parseCSV('A;B\n"ab;1'),/aspas/);
 assert.deepEqual(parseCSV('A,B\nfoo,2'),[['A','B'],['foo','2']]);assert.deepEqual(parseCSV('A\tB\nfoo\t2'),[['A','B'],['foo','2']]);
});
test('detecta cabeçalho abaixo de título e preserva cabeçalhos repetidos',()=>{
 const raw=[['Relatório'],[],['Data','Categoria','Valor','Valor'],['01/01/2026',' A ',10,20],['01/01/2026','A',10,20],[]];
 assert.equal(detectHeader(raw),2);const d=prepare(raw,2,{trim:true,deduplicate:true});
 assert.equal(d.rows.length,1);assert.equal(d.duplicates,1);assert.equal(d.emptyRows,1);assert.equal(d.columns[3].name,'Valor (2)');
});
test('finanças respeitam tipo, excluem valores inválidos e expõem tipos desconhecidos',()=>{
 const d=prepare([['Data','Categoria','Tipo','Valor'],['01/01/2026','A','Receita',100],['02/01/2026','B','Despesa',-30],['03/01/2026','B','Outro',45],['04/01/2026','B','Receita','erro']],0,rules);
 const map=inferMapping(d);map.metric=3;map.mode='finance';const s=analyze(d.rows,map);
 assert.equal(s.income,100);assert.equal(s.expense,30);assert.equal(s.balance,70);assert.equal(s.unclassified,1);assert.equal(s.invalid,1);
 const filtered=filterRows(d,map,{search:'despesa',category:'all',start:'2026-01-01',end:'2026-01-31'});
 assert.equal(filtered.length,1);assert.equal(analyze(filtered,map).balance,-30);
});
test('tipo ausente usa o sinal do valor, datas ausentes são sinalizadas',()=>{
 const d=prepare([['Data','Valor'],['2026-01-01',100],['',-40]],0,rules);
 const s=analyze(d.rows,{metric:1,group:-1,date:0,type:-1,mode:'finance',currency:true});
 assert.equal(s.balance,60);assert.equal(s.undated,1);assert.equal(s.timeline.length,1);
});
test('escolhe Valor antes de Quantidade para a análise de vendas',()=>{
 const d=prepare(demoBook('sales').sheets[0].data,0,rules);assert.equal(d.columns[inferMapping(d).metric].name,'Valor');
});
test('CSV exportado neutraliza fórmulas textuais e mantém números negativos',()=>{
 const d=prepare([['Nome','Valor'],['=HYPERLINK("x")',-12]],0,rules);const csv=toCSV(d.columns,d.rows);assert.match(csv,/'=HYPERLINK/);assert.match(csv,/"-12"/);assert.equal(parseCSV(csv)[1][1],'-12');
});
test('demonstração financeira reconcilia com todos os registros e agrupamentos',()=>{
 const d=prepare(demoBook().sheets[0].data,0,rules);const s=analyze(d.rows,inferMapping(d));assert.equal(d.rows.length,128);assert.equal(s.income,176200);assert.equal(s.expense,92408);assert.equal(s.balance,83792);assert.equal(s.groups.reduce((n,g)=>n+g.value,0),s.expense);
});
test('dados só textuais produzem contagem e análise vazia não gera NaN',()=>{
 const d=prepare([['Nome','Equipe'],['Ana','A'],['Bia','B']],0,rules);const map=inferMapping(d);assert.equal(map.metric,-1);assert.equal(analyze(d.rows,map).groups.reduce((s,g)=>s+g.value,0),2);assert.equal(analyze([],map).average,0);
});

