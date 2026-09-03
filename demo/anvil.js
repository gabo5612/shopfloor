/* anvil — lógica determinista portada del backend Python.
   Lo que corre acá es idéntico a lo que corre en el servidor:
     · búsqueda léxica          (retrieve.py, rama léxica)
     · detección de ambigüedad  (ambiguity.py)
     · verificador de datos     (verify.py)
     · guard del caché          (cache.py, comparación de términos)
   Lo único que NO corre es lo que necesita un modelo: el embedding de la
   pregunta y la redacción. Ver el aviso del pie. */

export const STOP = new Set(['cual','cuales','que','como','donde','es','el','la','los',
  'las','de','del','un','una','para','por','en','y','o','a','al','se','su','sus',
  'the','of','is','what','which','where','how','and','or','to','for','in','on','with']);

export const tokens = t => (t.toLowerCase().match(/[\w.-]{2,}/g) || []).filter(w => !STOP.has(w));

/* --- verify.py --- */
const TOKEN_RE = /\b[A-Z](?:[-.\s]?[A-Z]){0,4}[-.\s]{0,2}\d{1,6}(?:[-.]\d{1,4})*\b|\b\d+(?:[.,]\d+)+\b|\b\d{1,9}\b/g;
const IGNORE_RE = /\[\d+\]|p[aá]g(?:ina)?s?\.?\s*\d+|page\s*\d+/gi;
const norm = s => s.replace(/[\s.\-,]/g, '').toUpperCase();

export function extractFacts(text){
  const cleaned = text.replace(IGNORE_RE, ' ');
  return new Set((cleaned.match(TOKEN_RE) || []).map(norm));
}
export function verify(answer, citedTexts){
  const supported = new Set();
  for (const t of citedTexts) for (const f of extractFacts(t)) supported.add(f);
  const claimed = [...extractFacts(answer)];
  const unsupported = claimed.filter(f => !supported.has(f));
  return { passed: unsupported.length === 0, unsupported, checked: claimed.length };
}

/* --- cache.py: mismo guard determinista --- */
const TERM_RE = /[A-Za-z]{1,6}[-.]?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\b/g;
export const termsOf = q =>
  [...new Set((q.match(TERM_RE) || []).map(t => t.toLowerCase().replace(',', '.')))].sort();

/* --- ambiguity.py --- */
const AMB_TERM = /[A-Za-z]{1,5}[-.]?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/g;
const termSet = t => new Set((t.match(AMB_TERM) || []).map(x => x.toLowerCase().replace(',', '.')));

export function parseTables(text){
  const tables = []; let header = null, rows = [];
  const flush = () => { if (header && rows.length) tables.push({header, rows}); header = null; rows = []; };
  for (const line of text.split('\n')){
    if (!line.includes('|')) { flush(); continue; }
    if (/^[\s|:-]+$/.test(line)) continue;
    const cells = line.trim().replace(/^\||\|$/g, '').split(/\s*\|\s*/).map(c => c.trim());
    if (!header) header = cells; else rows.push(cells);
  }
  flush(); return tables;
}

export function detectAmbiguity(question, chunks){
  const q = termSet(question);
  if (!q.size) return null;
  for (const chunk of chunks){
    for (const t of parseTables(chunk)){
      const n = t.header.length;
      const scored = t.rows.filter(r => r.length === n)
        .map(r => [[...termSet(r.join(' '))].filter(x => q.has(x)).length, r]);
      const best = Math.max(0, ...scored.map(s => s[0]));
      if (!best) continue;
      const matches = scored.filter(s => s[0] === best).map(s => s[1]);
      if (matches.length < 2) continue;
      for (let i = 0; i < n; i++){
        const uniq = [...new Set(matches.map(r => r[i]))];
        if (uniq.length < 2) continue;
        if ([...termSet(uniq.join(' '))].some(x => q.has(x))) continue;
        const othersDiffer = [...Array(n).keys()].some(j =>
          j !== i && new Set(matches.map(r => r[j])).size > 1);
        if (!othersDiffer) continue;
        return { question: `¿Para qué ${(t.header[i] || `columna ${i+1}`).toLowerCase()}?`,
                 options: uniq };
      }
    }
  }
  return null;
}

/* --- retrieve.py, rama léxica: OR + ts_rank aproximado --- */
export function search(question, data, k = 6){
  const qs = tokens(question);
  if (!qs.length) return [];
  const score = new Map();
  const N = data.chunks.length;
  for (const t of qs){
    const posting = data.index[t];
    if (!posting) continue;
    const idf = Math.log(1 + N / posting.length);   // término raro pesa más
    for (const i of posting) score.set(i, (score.get(i) || 0) + idf);
  }
  return [...score.entries()].sort((a, b) => b[1] - a[1]).slice(0, k)
    .map(([i, s]) => ({ ...data.chunks[i], score: +s.toFixed(3),
                        doc: data.docs.find(d => d.doc_id === data.chunks[i].doc) }));
}

/* --- cache: acierto = mismos términos exactos (la similitud no basta) --- */
export function cacheLookup(question, data){
  const want = termsOf(question).join('|');
  if (!want) return null;
  const qt = new Set(tokens(question));
  let best = null, bestOverlap = 0;
  for (const e of data.cache){
    if (e.terms.join('|') !== want) continue;         // guard determinista
    const et = new Set(tokens(e.q));
    const overlap = [...qt].filter(t => et.has(t)).length / Math.max(qt.size, et.size, 1);
    if (overlap > bestOverlap){ bestOverlap = overlap; best = e; }
  }
  return best && bestOverlap >= 0.5 ? { ...best, overlap: bestOverlap } : null;
}
