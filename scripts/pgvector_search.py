"""Query the local pgvector corpus with the same E5 passage/query contract."""
from __future__ import annotations
import argparse, json
import sys

def main():
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap=argparse.ArgumentParser(); ap.add_argument("query"); ap.add_argument("--dsn",default="postgresql://dog_rag:dog_rag_local@localhost:5433/dog_rag"); ap.add_argument("--model",default="intfloat/multilingual-e5-base"); ap.add_argument("--top-k",type=int,default=5); args=ap.parse_args()
    import psycopg
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(args.model); vec=model.encode("query: "+args.query,normalize_embeddings=True)
    vector="["+",".join(str(float(x)) for x in vec)+"]"
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("""select chunk_id,document_id,chunk_index,text,metadata,1-(embedding <=> %s::vector) as score from rag_chunks where embedding_model=%s order by embedding <=> %s::vector limit %s""",(vector,args.model,vector,args.top_k))
        rows=cur.fetchall()
    print(json.dumps([{"chunk_id":r[0],"document_id":r[1],"chunk_index":r[2],"text":r[3][:500],"metadata":r[4],"score":round(float(r[5]),6)} for r in rows],ensure_ascii=False,indent=2))
if __name__=="__main__": main()
